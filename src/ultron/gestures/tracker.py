"""Turns noisy per-frame hand detections into stable poses and events.

Production rules that keep gestures from firing by accident:

* **Engagement:** a hand counts only when it is fully inside the picture (a hand
  cut off by the frame edge cannot be read reliably) and close enough to the
  camera. Height in the frame does not matter.
* **Left and right:** MediaPipe's handedness label is used, but two hands with
  the same label are told apart by position (your right hand is on the right of
  the mirrored picture), and a single hand keeps its side while it moves.
* **Hysteresis:** a pose becomes active only after ``POSE_CONFIRM_FRAMES``
  consistent frames and ends only after ``POSE_RELEASE_FRAMES`` frames of
  something else, so one bad frame never starts or ends a gesture.
* **Exit gesture:** both palms open toward the camera for ``EXIT_HOLD_SEC``.
* **Idle timeout:** no engaged hand for ``IDLE_TIMEOUT_SEC`` ends gesture mode.

Pure logic (no camera, no MediaPipe), driven by ``update()`` once per frame.
"""
from dataclasses import dataclass, field
import math

from ultron.gestures.filters import LandmarkFilter
from ultron.gestures.hands import classify, features

FRAME_MARGIN = 0.005  # every landmark must be at least this far inside the image
MIN_PALM_SIZE = 0.05  # in image units: smaller means too far away
SAME_HAND_DISTANCE = 0.15  # palm centre movement (image units) still the same hand
POSE_CONFIRM_FRAMES = 3
POSE_RELEASE_FRAMES = 4
EXIT_HOLD_SEC = 1.0
IDLE_TIMEOUT_SEC = 180.0
LOST_AFTER_SEC = 0.35  # a hand missing this long is gone


@dataclass
class HandState:
    side: str  # 'Right' or 'Left' (the user's real hand)
    landmarks: list = field(default_factory=list)  # smoothed
    centre: tuple = (0.5, 0.5)  # raw palm centre, for keeping track of sides
    pose: str = 'unknown'  # confirmed pose
    candidate: str = 'unknown'
    candidate_frames: int = 0
    engaged: bool = False
    near: bool = False  # close enough to the camera (pointer may use a hand cut by the frame edge)
    pinch: float = 1.0  # thumb-index tips in palm sizes, from 3D landmarks when available
    pinch_2d: float = 1.0  # the same in the camera picture (raw), an assist for the pinch detector
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
        for side, landmarks, world in self._assign_sides(detections, now):
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
            hand.centre = raw.palm_center
            hand.landmarks = hand.filter(landmarks, now)
            # Smoothed image landmarks for position; the raw 3D landmarks for the
            # finger angles (MediaPipe already stabilises those across frames).
            try:
                smooth = features(hand.landmarks, world)
            except ValueError:
                smooth = features(hand.landmarks)
            hand.pinch = smooth.pinch
            hand.near = raw.palm_size > MIN_PALM_SIZE
            hand.pinch_2d = raw.pinch
            hand.engaged = hand.near and _inside_frame(landmarks)
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

    def _assign_sides(self, detections, now):
        """Yield (side, landmarks, world) with at most one hand per side.

        Detections are (label, landmarks, score[, world]) with landmarks in the
        mirrored picture (x grows to the user's right).
        """
        hands = []
        for detection in detections or ():
            if len(detection) < 3:
                continue
            label, landmarks, _score = detection[:3]
            world = detection[3] if len(detection) > 3 else None
            try:
                centre = features(landmarks).palm_center
            except ValueError:
                continue
            hands.append([label, landmarks, world, centre])
        hands = hands[:2]
        if len(hands) == 2:
            a, b = hands
            if a[0] == b[0] or a[0] not in ('Right', 'Left') or b[0] not in ('Right', 'Left'):
                # Same (or unknown) label for both: the one further right is the right hand.
                a[0], b[0] = ('Right', 'Left') if a[3][0] > b[3][0] else ('Left', 'Right')
        elif len(hands) == 1:
            hand = hands[0]
            recent = [h for h in self.hands.values() if now - h.last_seen <= LOST_AFTER_SEC]
            if len(recent) == 1 and math.dist(recent[0].centre, hand[3]) < SAME_HAND_DISTANCE:
                hand[0] = recent[0].side  # the same hand moving: keep its side
        for label, landmarks, world, _centre in hands:
            if label in ('Right', 'Left'):
                yield label, landmarks, world

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


def _inside_frame(landmarks):
    return all(FRAME_MARGIN <= p[0] <= 1 - FRAME_MARGIN and FRAME_MARGIN <= p[1] <= 1 - FRAME_MARGIN
               for p in landmarks)
