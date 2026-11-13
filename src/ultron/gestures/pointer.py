"""Air mouse (stage G2): turns the dominant hand into pointer commands.

Pure logic, driven once per camera frame with the tracker's state of the
dominant hand. It never touches the desktop: it returns small commands that the
vision service sends to the action daemon on ``ultron.pointer``, where the
mouse is actually moved (only while gesture mode is on).

How it behaves:

* **Move** while the hand is pointing (index up) or pinching. The cursor follows
  the index knuckle, not the fingertip, so closing a pinch does not jerk it.
  A comfortable central area of the camera picture covers the whole desktop.
* **Pinch tap** (thumb touches index and lets go within ``TAP_MAX_SEC``) clicks.
  The cursor freezes for the first moments of a pinch so a tap clicks exactly
  where you aimed. Two taps close together are a double-click.
* **Pinch hold** presses the button and drags until the pinch opens.
* **Victory sign** moved up or down scrolls.
* Losing the hand, leaving the pose or ending gesture mode always releases the
  button, so it can never stay pressed.

Pinch uses the 3D thumb-to-index distance with hysteresis (press below
``PINCH_PRESS``, release above ``PINCH_RELEASE``, in palm sizes), so a
half-closed hand neither clicks nor flickers.
"""
from dataclasses import dataclass, field

from ultron.gestures.filters import OneEuroFilter

POINTER_SUBJECT = 'ultron.pointer'

# Region of the mirrored camera picture (x0, y0, x1, y1) that covers the whole
# desktop: reaching the corners of the picture is tiring and tracking is weakest
# at the edges, so a central area is used.
ACTIVE_AREA = (0.18, 0.15, 0.82, 0.75)
PINCH_PRESS = 0.30  # thumb-index tips / palm size; touching is about 0.28
PINCH_RELEASE = 0.42
TAP_MAX_SEC = 0.32  # pinch shorter than this is a click; longer starts a drag
DOUBLE_TAP_SEC = 0.45  # second tap within this after the first: double-click
FREEZE_SEC = 0.22  # cursor holds still at the start of a pinch
DEAD_ZONE = 0.0012  # ignore cursor moves smaller than this (fraction of desktop)
SCROLL_NOTCHES_PER_FRAME = 30.0  # wheel notches for a full picture-height move
WHEEL_DELTA = 120  # Windows: one notch
MOVE_POSES = frozenset({'point', 'pinch'})
SCROLL_POSE = 'victory'
KNUCKLE = 5  # index finger base (MCP)

ACTIONS = ('pointer.move', 'pointer.click', 'pointer.double_click', 'pointer.drag', 'pointer.scroll')


def _clamp01(value):
    return min(1.0, max(0.0, value))


def to_desktop(x, y, area=ACTIVE_AREA):
    """Mirrored picture coordinates to desktop fractions (0..1)."""
    x0, y0, x1, y1 = area
    return _clamp01((x - x0) / (x1 - x0)), _clamp01((y - y0) / (y1 - y0))


@dataclass
class AirMouse:
    enabled: frozenset = frozenset(ACTIONS)
    filter_x: OneEuroFilter = field(default_factory=lambda: OneEuroFilter(min_cutoff=0.8, beta=0.03))
    filter_y: OneEuroFilter = field(default_factory=lambda: OneEuroFilter(min_cutoff=0.8, beta=0.03))
    position: tuple | None = None  # last cursor position sent
    pinching: bool = False
    pinch_since: float = 0.0
    pressed: bool = False  # button held for a drag
    last_tap: float = -1e9
    scroll_y: float | None = None
    scroll_rest: float = 0.0
    active: bool = False

    def update(self, hand, now):
        """Feed the dominant hand (tracker state or None). Returns (commands, events)."""
        commands, events = [], []
        usable = hand is not None and hand.engaged and len(hand.landmarks) == 21
        pose = hand.pose if usable else 'unknown'
        moving = usable and (pose in MOVE_POSES or self.pinching)

        # Scroll: victory sign moved up or down.
        if usable and pose == SCROLL_POSE and 'pointer.scroll' in self.enabled and not self.pinching:
            y = hand.landmarks[KNUCKLE][1]
            if self.scroll_y is not None:
                self.scroll_rest += (self.scroll_y - y) * SCROLL_NOTCHES_PER_FRAME  # hand up: scroll up
                notches = int(self.scroll_rest)
                if notches:
                    self.scroll_rest -= notches
                    commands.append({'op': 'scroll', 'delta': notches * WHEEL_DELTA})
                    events.append({'type': 'pointer', 'action': 'scroll', 'notches': notches})
            self.scroll_y = y
        else:
            self.scroll_y, self.scroll_rest = None, 0.0

        if not moving:
            commands += self._release(now, events)
            self.active = False
            return commands, events

        if not self.active:
            self.filter_x.reset()
            self.filter_y.reset()
            self.active = True

        # Pinch with hysteresis on the 3D thumb-index distance.
        if not self.pinching and hand.pinch < PINCH_PRESS:
            self.pinching, self.pinch_since = True, now
        elif self.pinching and hand.pinch > PINCH_RELEASE:
            self.pinching = False
            commands += self._pinch_released(now, events)

        # A pinch held long enough becomes a drag.
        if (self.pinching and not self.pressed and now - self.pinch_since >= TAP_MAX_SEC
                and 'pointer.drag' in self.enabled):
            self.pressed = True
            commands.append({'op': 'down'})
            events.append({'type': 'pointer', 'action': 'drag_start'})

        frozen = self.pinching and not self.pressed and now - self.pinch_since < max(FREEZE_SEC, TAP_MAX_SEC)
        if 'pointer.move' in self.enabled and not frozen:
            x, y = to_desktop(*hand.landmarks[KNUCKLE][:2])
            x, y = self.filter_x(x, now), self.filter_y(y, now)
            if self.position is None or max(abs(x - self.position[0]), abs(y - self.position[1])) >= DEAD_ZONE:
                self.position = (x, y)
                commands.insert(0, {'op': 'move', 'x': round(x, 5), 'y': round(y, 5)})
        return commands, events

    def _pinch_released(self, now, events):
        if self.pressed:
            self.pressed = False
            events.append({'type': 'pointer', 'action': 'drag_end'})
            return [{'op': 'up'}]
        if now - self.pinch_since < TAP_MAX_SEC:
            double = now - self.last_tap <= DOUBLE_TAP_SEC
            self.last_tap = -1e9 if double else now
            action = 'pointer.double_click' if double else 'pointer.click'
            # A double-click is the second of two clicks in quick succession at
            # the same spot; Windows recognises it from the timing.
            if action in self.enabled or (double and 'pointer.click' in self.enabled):
                events.append({'type': 'pointer', 'action': 'double_click' if double else 'click'})
                return [{'op': 'click'}]
        return []

    def _release(self, now, events):
        """Hand gone or pose left: end any pinch; never leave the button down."""
        self.pinching = False
        if self.pressed:
            self.pressed = False
            events.append({'type': 'pointer', 'action': 'drag_end'})
            return [{'op': 'up'}]
        return []

    def reset(self, now=0.0):
        """Gesture mode ended: release everything."""
        events = []
        commands = self._release(now, events)
        self.active = False
        self.position = None
        self.scroll_y, self.scroll_rest = None, 0.0
        return commands, events


def enabled_actions(config, live_stages):
    """Pointer actions the gesture config maps for the dominant hand in a live stage."""
    return frozenset(m.action for m in config.mappings
                     if m.action in ACTIONS and m.hands == 'dominant' and m.stage in live_stages)
