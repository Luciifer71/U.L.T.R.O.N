"""Hand geometry and static pose recognition from 21 MediaPipe hand landmarks.

Landmarks are (x, y, z) in image-normalised units: x and y in 0..1 (origin top
left, y down), z relative depth. Frames are mirrored before detection, so the
picture behaves like a mirror and ``handedness`` matches the user's real hand.

All measurements are ratios of the palm size, so they work at any distance from
the camera and for any hand size. Everything here is pure maths (no camera, no
MediaPipe), so it is unit tested with recorded or synthetic landmarks.
"""
from dataclasses import dataclass
import math

WRIST = 0
THUMB = (1, 2, 3, 4)
INDEX = (5, 6, 7, 8)
MIDDLE = (9, 10, 11, 12)
RING = (13, 14, 15, 16)
PINKY = (17, 18, 19, 20)
FINGERS = {'index': INDEX, 'middle': MIDDLE, 'ring': RING, 'pinky': PINKY}

# Skeleton for drawing (pairs of landmark indices).
CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
)

POSES = (
    'open_palm', 'fist', 'point', 'pinch', 'victory', 'three',
    'thumbs_up', 'thumbs_down', 'ok', 'rock', 'unknown',
)

# A finger counts as extended when its tip is this much farther from the wrist
# than its middle joint (ratio), i.e. the finger is straightened out.
EXTENDED_RATIO = 1.12
# Thumb tip to index base, in palm sizes, for the thumb to count as extended.
THUMB_EXTENDED = 0.62
# Thumb tip to index tip, in palm sizes, for a pinch.
PINCH_CLOSE = 0.33


def distance(a, b):
    return math.dist(a[:3] if len(a) > 2 else (*a, 0.0), b[:3] if len(b) > 2 else (*b, 0.0))


@dataclass(frozen=True)
class HandFeatures:
    palm_size: float
    extended: dict  # finger name -> bool, including 'thumb'
    pinch: float  # thumb-index tip distance in palm sizes
    palm_center: tuple  # (x, y) in image units
    thumb_direction: float  # thumb tip above (+) / below (-) its base, in palm sizes


def features(landmarks):
    """Scale-independent description of one hand. Raises ValueError on bad input."""
    if landmarks is None or len(landmarks) != 21:
        raise ValueError('a hand needs exactly 21 landmarks')
    pts = [tuple(float(v) for v in p) for p in landmarks]
    palm = distance(pts[WRIST], pts[MIDDLE[0]])
    if not math.isfinite(palm) or palm < 1e-4:
        raise ValueError('degenerate hand (palm size zero)')
    wrist = pts[WRIST]
    extended = {}
    for name, (base, middle, _, tip) in FINGERS.items():
        extended[name] = distance(pts[tip], wrist) > distance(pts[middle], wrist) * EXTENDED_RATIO
    extended['thumb'] = distance(pts[THUMB[3]], pts[INDEX[0]]) / palm > THUMB_EXTENDED
    centre_ids = (WRIST, INDEX[0], MIDDLE[0], RING[0], PINKY[0])
    cx = sum(pts[i][0] for i in centre_ids) / len(centre_ids)
    cy = sum(pts[i][1] for i in centre_ids) / len(centre_ids)
    return HandFeatures(
        palm_size=palm,
        extended=extended,
        pinch=distance(pts[THUMB[3]], pts[INDEX[3]]) / palm,
        palm_center=(cx, cy),
        thumb_direction=(pts[THUMB[0]][1] - pts[THUMB[3]][1]) / palm,
    )


def classify(f):
    """Name the static pose of a hand from its features (see ``POSES``)."""
    e = f.extended
    fingers = (e['index'], e['middle'], e['ring'], e['pinky'])
    count = sum(fingers)
    if f.pinch < PINCH_CLOSE:
        # Thumb and index touching: OK sign if the other three are up, else a pinch.
        return 'ok' if e['middle'] and e['ring'] and e['pinky'] else 'pinch'
    if count == 4 and e['thumb']:
        return 'open_palm'
    if count == 0:
        if e['thumb'] and f.thumb_direction > 0.45:
            return 'thumbs_up'
        if e['thumb'] and f.thumb_direction < -0.45:
            return 'thumbs_down'
        return 'fist'
    if fingers == (True, False, False, False):
        return 'point'
    if fingers == (True, True, False, False):
        return 'victory'
    if fingers == (True, True, True, False):
        return 'three'
    if fingers == (True, False, False, True):
        return 'rock'
    return 'unknown'


def pose_of(landmarks):
    return classify(features(landmarks))
