"""Air mouse (stage G2): turns the dominant hand into pointer commands.

Pure logic, driven once per camera frame with the tracker's state of the
dominant hand. It never touches the desktop: it returns small commands that the
vision service sends to the action daemon on ``ultron.pointer``, where the
mouse is actually moved (only while gesture mode is on).

It works like a real mouse button:

* **Move**: the cursor follows the index knuckle (not the fingertip, so closing
  a pinch does not jerk it) whatever the other fingers do. A **fist** is a
  clutch, like lifting a mouse: the cursor stays put while you reposition.
  A comfortable central area of the camera picture covers the whole desktop.
* **Pinch = button down, open = button up.** Windows itself turns that into a
  click or, for two quick taps, a double-click; holding and moving is a drag.
  The pinch is recognised from the thumb and index tips alone, whatever pose
  the other fingers are in and however the hand is turned.
* **Pinpoint presses:** closing a pinch nudges the hand, so the press lands
  where the cursor was just *before* the pinch began, and the cursor stays
  locked during the press until the hand clearly moves (``SLOP``); only then
  does a drag start. A second tap close in time and place lands on exactly
  the same spot, so Windows always sees a double-click.
* **Adapts to the user:** the pinch thresholds follow each person's measured
  "touching" and "open" distances (see ``PinchDetector``).
* **Victory sign** moved up or down scrolls.
* Losing the hand, a fist, or leaving gesture mode always releases the button,
  so it can never stay pressed.
"""
from collections import deque
from dataclasses import dataclass, field
import math

from ultron.gestures.filters import OneEuroFilter

POINTER_SUBJECT = 'ultron.pointer'

# Region of the mirrored camera picture (x0, y0, x1, y1) that covers the whole
# desktop: reaching the corners of the picture is tiring and tracking is weakest
# at the edges, so a central area is used.
ACTIVE_AREA = (0.18, 0.15, 0.82, 0.75)
DEAD_ZONE = 0.0012  # ignore cursor moves smaller than this (fraction of desktop)
SLOP = 0.014  # hand movement during a press before it becomes a drag (fraction of desktop)
SLOP_FRAMES = 2  # ... sustained for this many frames, so camera jitter never starts a drag
REWIND_SEC = 0.12  # a press lands where the cursor was this long before the pinch registered
RELEASE_HOLD_SEC = 0.12  # cursor stays put briefly after a release (opening a pinch also nudges the hand)
DOUBLE_TAP_SEC = 0.5  # a second press this soon ...
DOUBLE_TAP_RADIUS = 0.02  # ... and this close to the first lands on exactly the same spot
CLICK_MAX_SEC = 0.6  # a press shorter than this without moving is reported as a click
LOSS_GRACE_SEC = 0.25  # a hand lost this briefly (one bad camera frame) keeps the button down
SCROLL_NOTCHES_PER_FRAME = 30.0  # wheel notches for a full picture-height move
WHEEL_DELTA = 120  # Windows: one notch
SCROLL_POSE = 'victory'
CLUTCH_POSE = 'fist'
KNUCKLE = 5  # index finger base (MCP)
THUMB_TIP, INDEX_TIP = 4, 8
TIP_MARGIN = 0.004  # pinch tips must be inside the picture to be judged

ACTIONS = ('pointer.move', 'pointer.click', 'pointer.double_click', 'pointer.drag', 'pointer.scroll')


def _clamp01(value):
    return min(1.0, max(0.0, value))


def to_desktop(x, y, area=ACTIVE_AREA):
    """Mirrored picture coordinates to desktop fractions (0..1)."""
    x0, y0, x1, y1 = area
    return _clamp01((x - x0) / (x1 - x0)), _clamp01((y - y0) / (y1 - y0))


@dataclass
class PinchDetector:
    """Thumb-index pinch with hysteresis that adapts to each user.

    Distances are thumb-to-index tip in palm sizes from MediaPipe's 3D
    landmarks. Measured on real hands: touching tips read about 0.2-0.3, a fist
    0.36 (thumb resting over the index), open hands 0.77-0.91. People, cameras
    and hand angles differ, so the detector learns each user's touching level
    from the average reading during their pinches and presses a little above it, but
    never above ``PRESS_MAX`` so a fist can never click. A strong 2D cue (tips
    together in the picture) helps when the 3D estimate is slightly high, e.g.
    when the thumb hides the index tip.
    """
    touch: float = 0.22
    pressed: bool = False
    total: float = 0.0  # sum and count of distances during the current pinch
    count: int = 0
    open_frames: int = 0
    wide_frames: int = 0

    PRESS_MARGIN = 0.08  # press this far above the user's touching level ...
    PRESS_MIN, PRESS_MAX = 0.24, 0.33  # ... within these bounds (a fist reads 0.36)
    RELEASE_GAP = 0.10  # release this far above the press threshold (hysteresis)
    TWO_D_TOUCH = 0.16  # 2D tip distance (palm sizes) that counts as touching in the picture
    TWO_D_SLACK = 0.03  # the 2D cue may press at most this far above the 3D threshold
    RELEASE_FRAMES = 3  # open this many frames in a row to release, so bad readings never let go ...
    QUICK_RELEASE_FRAMES = 2  # ... or this many when the hand is clearly wide open
    WIDE_OPEN = 0.2  # this far above the release threshold counts as clearly open

    def thresholds(self):
        press = min(self.PRESS_MAX, max(self.PRESS_MIN, self.touch + self.PRESS_MARGIN))
        return press, press + self.RELEASE_GAP

    def update(self, distance, distance_2d=None):
        """Feed one frame. Returns 'press', 'release' or None."""
        if not (isinstance(distance, (int, float)) and math.isfinite(distance)):
            return None
        press, release = self.thresholds()
        touching_2d = isinstance(distance_2d, (int, float)) and distance_2d < self.TWO_D_TOUCH
        if not self.pressed:
            if distance < press or (touching_2d and distance < press + self.TWO_D_SLACK):
                self.pressed, self.total, self.count = True, distance, 1
                self.open_frames = self.wide_frames = 0
                return 'press'
            return None
        if distance > release:
            self.open_frames += 1
            self.wide_frames = self.wide_frames + 1 if distance > release + self.WIDE_OPEN else 0
        else:
            self.open_frames = self.wide_frames = 0
            self.total, self.count = self.total + distance, self.count + 1
        if self.open_frames >= self.RELEASE_FRAMES or self.wide_frames >= self.QUICK_RELEASE_FRAMES:
            self.pressed, self.open_frames, self.wide_frames = False, 0, 0
            # Learn how close this user's tips read when they touch: the average
            # over the pinch (the closest single reading is biased low by noise).
            typical = self.total / max(1, self.count)
            self.touch += 0.3 * (min(max(typical, 0.05), 0.3) - self.touch)
            return 'release'
        return None

    def cancel(self):
        self.pressed, self.open_frames, self.wide_frames = False, 0, 0


@dataclass
class AirMouse:
    enabled: frozenset = frozenset(ACTIONS)
    filter_x: OneEuroFilter = field(default_factory=lambda: OneEuroFilter(min_cutoff=0.8, beta=0.03))
    filter_y: OneEuroFilter = field(default_factory=lambda: OneEuroFilter(min_cutoff=0.8, beta=0.03))
    pinch: PinchDetector = field(default_factory=PinchDetector)
    history: deque = field(default_factory=lambda: deque(maxlen=12))  # (time, x, y) of the tracked hand
    position: tuple | None = None  # last cursor position sent
    pressed: bool = False  # button is down
    press_time: float = 0.0
    press_hand: tuple | None = None  # unsmoothed hand position when the press began
    dragging: bool = False
    hold_until: float = 0.0
    last_click: tuple | None = None  # (time, x, y) of the last click, for double-clicks
    scroll_y: float | None = None
    scroll_rest: float = 0.0
    active: bool = False
    lost_since: float | None = None
    recent: deque = field(default_factory=lambda: deque(maxlen=3))  # unsmoothed hand positions
    beyond_slop: int = 0

    def update(self, hand, now):
        """Feed the dominant hand (tracker state or None). Returns (commands, events)."""
        commands, events = [], []
        landmarks = getattr(hand, 'landmarks', None) or []
        near = getattr(hand, 'near', getattr(hand, 'engaged', False))
        usable = hand is not None and near and len(landmarks) == 21 and _tips_visible(landmarks)
        pose = hand.pose if usable else 'unknown'

        if usable and pose == SCROLL_POSE and not self.pressed:
            self._scroll(landmarks, commands, events)
            self.active = False
            return commands, events
        self.scroll_y, self.scroll_rest = None, 0.0

        if not usable and self.pressed:
            # Keep the button down through a brief loss; let go if it lasts.
            self.lost_since = now if self.lost_since is None else self.lost_since
            if now - self.lost_since < LOSS_GRACE_SEC:
                return commands, events
        if not usable or (pose == CLUTCH_POSE and not self.pressed):
            commands += self._release(now, events)
            self.active = False
            self.lost_since = None
            return commands, events
        self.lost_since = None

        if not self.active:
            self.filter_x.reset()
            self.filter_y.reset()
            self.history.clear()
            self.recent.clear()
            self.active = True
        current = to_desktop(*landmarks[KNUCKLE][:2])
        self.recent.append(current)
        # Average of the last few unsmoothed positions: quick to follow the hand
        # (no catch-up lag like the cursor filter) yet steady against jitter.
        raw = (sum(p[0] for p in self.recent) / len(self.recent), sum(p[1] for p in self.recent) / len(self.recent))
        x, y = self.filter_x(current[0], now), self.filter_y(current[1], now)
        self.history.append((now, x, y))

        clicking = 'pointer.click' in self.enabled
        change = self.pinch.update(hand.pinch, getattr(hand, 'pinch_2d', None)) if clicking else None
        if pose == CLUTCH_POSE and self.pressed:
            change = 'release'  # closing to a fist mid-press lets go
            self.pinch.cancel()
        if change == 'press':
            commands += self._press(now, (x, y), raw)
        elif change == 'release' and self.pressed:
            commands += self._finish(now, events)
            self.hold_until = now + RELEASE_HOLD_SEC

        if self.pressed and not self.dragging:
            # Judge movement on the unsmoothed hand: the smoothed cursor may still
            # be catching up with a hand that just arrived, which is not a drag.
            self.beyond_slop = self.beyond_slop + 1 if math.dist(raw, self.press_hand) > SLOP else 0
            if self.beyond_slop >= SLOP_FRAMES and 'pointer.drag' in self.enabled:
                self.dragging = True
                events.append({'type': 'pointer', 'action': 'drag_start'})

        locked = (self.pressed and not self.dragging) or now < self.hold_until
        if 'pointer.move' in self.enabled and not locked:
            if self.position is None or max(abs(x - self.position[0]), abs(y - self.position[1])) >= DEAD_ZONE:
                self.position = (x, y)
                commands.append({'op': 'move', 'x': round(x, 5), 'y': round(y, 5)})
        return commands, events

    # ---- button --------------------------------------------------------
    def _press(self, now, hand_position, raw):
        target = self._aim(now, hand_position)
        last = self.last_click
        if last and now - last[0] <= DOUBLE_TAP_SEC and math.dist(target, last[1:]) <= DOUBLE_TAP_RADIUS:
            target = last[1:]  # exactly the same spot, so Windows sees a double-click
        self.pressed, self.press_time, self.dragging = True, now, False
        self.press_hand, self.beyond_slop = raw, 0
        self.position = target
        return [{'op': 'move', 'x': round(target[0], 5), 'y': round(target[1], 5)}, {'op': 'down'}]

    def _aim(self, now, fallback):
        """Where the cursor was just before the pinch started to close."""
        aim = None
        for t, x, y in self.history:
            if t <= now - REWIND_SEC:
                aim = (x, y)
        if aim is None and self.history:
            aim = self.history[0][1:]
        if aim is None:
            aim = fallback
        # Never jump: if the hand had not been tracked for long, use the current spot.
        if self.position is not None and math.dist(aim, self.position) > 3 * SLOP:
            aim = self.position
        return aim

    def _finish(self, now, events):
        self.pressed = False
        if self.dragging:
            self.dragging = False
            events.append({'type': 'pointer', 'action': 'drag_end'})
        elif now - self.press_time <= CLICK_MAX_SEC:
            last = self.last_click
            double = bool(last and self.press_time - last[0] <= DOUBLE_TAP_SEC and self.position == last[1:])
            events.append({'type': 'pointer', 'action': 'double_click' if double else 'click'})
            self.last_click = None if double else (now, *self.position)
        return [{'op': 'up'}]

    def _release(self, now, events):
        """Hand gone or clutch: never leave the button down."""
        self.pinch.cancel()
        if self.pressed:
            self.pressed = False
            if self.dragging:
                self.dragging = False
                events.append({'type': 'pointer', 'action': 'drag_end'})
            return [{'op': 'up'}]
        return []

    # ---- scroll --------------------------------------------------------
    def _scroll(self, landmarks, commands, events):
        if 'pointer.scroll' not in self.enabled:
            return
        y = landmarks[KNUCKLE][1]
        if self.scroll_y is not None:
            self.scroll_rest += (self.scroll_y - y) * SCROLL_NOTCHES_PER_FRAME  # hand up: scroll up
            notches = int(self.scroll_rest)
            if notches:
                self.scroll_rest -= notches
                commands.append({'op': 'scroll', 'delta': notches * WHEEL_DELTA})
                events.append({'type': 'pointer', 'action': 'scroll', 'notches': notches})
        self.scroll_y = y

    def reset(self, now=0.0):
        """Gesture mode ended: release everything."""
        events = []
        commands = self._release(now, events)
        self.active = False
        self.position = None
        self.last_click = None
        self.scroll_y, self.scroll_rest = None, 0.0
        return commands, events


def _tips_visible(landmarks):
    return all(TIP_MARGIN <= landmarks[i][0] <= 1 - TIP_MARGIN and TIP_MARGIN <= landmarks[i][1] <= 1 - TIP_MARGIN
               for i in (THUMB_TIP, INDEX_TIP, KNUCKLE))


def enabled_actions(config, live_stages):
    """Pointer actions the gesture config maps for the dominant hand in a live stage."""
    return frozenset(m.action for m in config.mappings
                     if m.action in ACTIONS and m.hands == 'dominant' and m.stage in live_stages)
