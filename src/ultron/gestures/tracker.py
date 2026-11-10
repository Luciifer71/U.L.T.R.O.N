"""Turns noisy per-frame hand detections into stable poses and events.

Production rules that keep gestures from firing by accident:

* **Engagement zone:** a hand counts only when it is raised into the frame
  (palm centre above ``ENGAGE_BELOW`` of the image height) and large enough to be
  near the user, so a hand resting on the desk or passing by is ignored.
* **Hysteresis:** a pose becomes active only after ``POSE_CONFIRM_FRAMES``
  consistent frames and ends only after ``POSE_RELEASE_FRAMES`` frames of
  something else, so one bad frame never starts or ends a gesture.
* **Exit gesture:** both palms open toward the camera for ``EXIT_HOLD_SEC``.
* **Idle timeout:** no engaged hand for ``IDLE_TIMEOUT_SEC`` ends gesture mode.

Pure logic (no camera, no MediaPipe), driven by ``update()`` once per frame.
"""
from dataclasses import dataclass, field

from ultron.gestures.filters import LandmarkFilter
from ultron.gestures.hands import classify, features

ENGAGE_BELOW = 0.88  # palm centre y (0 = top, 1 = bottom of the image)
MIN_PALM_SIZE = 0.05  # in image units: smaller means too far away
POSE_CONFIRM_FRAMES = 3
POSE_RELEASE_FRAMES = 4
EXIT_HOLD_SEC = 1.0
IDLE_TIMEOUT_SEC = 180.0
LOST_AFTER_SEC = 0.35  # a hand missing this long is gone


@dataclass
class HandState:
    side: str  # 'Right' or 'Left' (the user's real hand)
    landmarks: list = field(default_factory=list)  # smoothed
    pose: str = 'unknown'  # confirmed pose
    candidate: str = 'unknown'
    candidate_frames: int = 0
    engaged: bool = False
    pinch: float = 1.0
    last_seen: float = 0.0
    filter: LandmarkFilter = field(default_factory=LandmarkFilter)


class GestureTracker:
    def __init__(self, idle_timeout=IDLE_TIMEOUT_SEC):
        self.hands = {}
        self.idle_timeout = idle_timeout
        self.last_engaged = None
        self.exit_since = None
        self.exited = False

    def reset(self, now):
        self.hands.clear()
        self.last_engaged = now
        self.exit_since = None
        self.exited = False

    def update(self, detections, now):
        """Feed one frame: a list of (side, 21 landmarks, score). Returns events.

        Events are dicts: {'type': 'pose', 'hand', 'pose', 'previous'},
        {'type': 'exit'} (both palms held) or {'type': 'idle'} (timeout).
        """
        if self.last_engaged is None:
            self.last_engaged = now
        events = []
        seen = set()
        for side, landmarks, _score in detections or ():
            if side in seen or side not in ('Right', 'Left'):
                continue  # one hand per side; ignore duplicates and unknowns
            try:
                raw = features(landmarks)
            except ValueError:
                continue
            seen.add(side)
            hand = self.hands.get(side) or HandState(side=side)
            if now - hand.last_seen > LOST_AFTER_SEC:
                hand.filter.reset()
            self.hands[side] = hand
            hand.last_seen = now
            hand.landmarks = hand.filter(landmarks, now)
            smooth = features(hand.landmarks)
            hand.pinch = smooth.pinch
            hand.engaged = raw.palm_center[1] < ENGAGE_BELOW and raw.palm_size > MIN_PALM_SIZE
            observed = classify(smooth) if hand.engaged else 'unknown'
            events.extend(self._stabilise(hand, observed))
        for side in list(self.hands):
            if side not in seen and now - self.hands[side].last_seen > LOST_AFTER_SEC:
                hand = self.hands.pop(side)
                if hand.pose != 'unknown':
                    events.append({'type': 'pose', 'hand': side, 'pose': 'unknown', 'previous': hand.pose})

        if any(h.engaged for h in self.hands.values()):
            self.last_engaged = now
        both_palms = len(self.hands) == 2 and all(
            h.engaged and h.pose == 'open_palm' for h in self.hands.values())
        if both_palms:
            self.exit_since = now if self.exit_since is None else self.exit_since
            if not self.exited and now - self.exit_since >= EXIT_HOLD_SEC:
                self.exited = True
                events.append({'type': 'exit'})
        else:
            self.exit_since = None
        if not self.exited and now - self.last_engaged >= self.idle_timeout:
            self.exited = True
            events.append({'type': 'idle'})
        return events

    @staticmethod
    def _stabilise(hand, observed):
        if observed == hand.pose:
            hand.candidate, hand.candidate_frames = observed, 0
            return []
        if observed == hand.candidate:
            hand.candidate_frames += 1
        else:
            hand.candidate, hand.candidate_frames = observed, 1
        needed = POSE_RELEASE_FRAMES if observed == 'unknown' else POSE_CONFIRM_FRAMES
        if hand.candidate_frames < needed:
            return []
        previous, hand.pose = hand.pose, observed
        hand.candidate_frames = 0
        return [{'type': 'pose', 'hand': hand.side, 'pose': observed, 'previous': previous}]

    def snapshot(self):
        """Compact, display-only view of the tracked hands (no image data)."""
        return [
            {
                'side': h.side,
                'pose': h.pose,
                'engaged': h.engaged,
                'pinch': round(h.pinch, 3),
                'points': [[round(v, 4) for v in p] for p in h.landmarks],
            }
            for h in self.hands.values()
        ]
