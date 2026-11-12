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

# --- 2D fallback (image landmarks only) ---------------------------------
# A finger counts as extended when its tip is this much farther from the wrist
# than its middle joint (ratio), i.e. the finger is straightened out.
EXTENDED_RATIO = 1.12
# Thumb tip to index base, in palm sizes, for the thumb to count as extended.
THUMB_EXTENDED = 0.62
# Thumb tip to index tip, in palm sizes, for a pinch.
PINCH_CLOSE = 0.33

# --- 3D (MediaPipe world landmarks, metres) -------------------------------
# Bend of a finger = angle at its middle joint + angle at its end joint, in
# degrees (0 = dead straight). Measured on real recordings: straight fingers
# 21-42, curled fingers 119-195. Between the two limits a finger is "unclear"
# and any pose that depends on it is reported as unknown rather than guessed.
FINGER_STRAIGHT_BELOW = 70.0
FINGER_CURLED_ABOVE = 100.0
# Thumb bend (MCP + IP joints): extended thumbs 32-43, tucked thumbs 86-111.
THUMB_STRAIGHT_BELOW = 60.0
THUMB_CURLED_ABOVE = 75.0
# Thumb tip to index tip, in metres, for the tips to count as touching.
PINCH_TOUCH_M = 0.025


def distance(a, b):
    return math.dist(a[:3] if len(a) > 2 else (*a, 0.0), b[:3] if len(b) > 2 else (*b, 0.0))


def _angle(u, v):
    nu, nv = math.hypot(*u), math.hypot(*v)
    if nu < 1e-9 or nv < 1e-9:
        return 0.0
    cos = sum(a * b for a, b in zip(u, v)) / (nu * nv)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def _bend(points, joints):
    """Sum of the angles at the last two joints of a finger (base, mid, end, tip)."""
    a, b, c, d = (points[i] for i in joints)
    seg = [tuple(q[k] - p[k] for k in range(3)) for p, q in ((a, b), (b, c), (c, d))]
    return _angle(seg[0], seg[1]) + _angle(seg[1], seg[2])


def _state(bend, straight_below, curled_above):
    if bend < straight_below:
        return True
    if bend > curled_above:
        return False
    return None  # unclear: do not guess


@dataclass(frozen=True)
class HandFeatures:
    palm_size: float  # wrist to middle-finger base, in image units
    extended: dict  # finger name -> True / False / None (unclear), including 'thumb'
    pinch: float  # thumb-index tip distance in palm sizes (0 = touching)
    palm_center: tuple  # (x, y) in image units
    thumb_direction: float  # thumb tip above (+) / below (-) its base, in palm sizes
    touching: bool = False  # thumb and index tips touching
    three_d: bool = False  # measured from world landmarks


def _points(landmarks):
    if landmarks is None or len(landmarks) != 21:
        raise ValueError('a hand needs exactly 21 landmarks')
    pts = []
    for p in landmarks:
        values = tuple(float(v) for v in p)
        if len(values) == 2:
            values = (*values, 0.0)
        if len(values) < 3 or not all(math.isfinite(v) for v in values[:3]):
            raise ValueError('landmarks must be finite numbers')
        pts.append(values[:3])
    return pts


def features(landmarks, world=None):
    """Scale-independent description of one hand. Raises ValueError on bad input.

    ``landmarks`` are image landmarks (for position and thumb direction). When
    ``world`` (MediaPipe's metric 3D landmarks) is given, fingers are judged by
    real joint angles, which do not change with distance or hand rotation.
    """
    pts = _points(landmarks)
    palm = distance(pts[WRIST], pts[MIDDLE[0]])
    if not math.isfinite(palm) or palm < 1e-4:
        raise ValueError('degenerate hand (palm size zero)')
    centre_ids = (WRIST, INDEX[0], MIDDLE[0], RING[0], PINKY[0])
    cx = sum(pts[i][0] for i in centre_ids) / len(centre_ids)
    cy = sum(pts[i][1] for i in centre_ids) / len(centre_ids)
    thumb_direction = (pts[THUMB[0]][1] - pts[THUMB[3]][1]) / palm

    if world is not None:
        w = _points(world)
        palm_m = distance(w[WRIST], w[MIDDLE[0]])
        if palm_m < 1e-4:
            raise ValueError('degenerate hand (palm size zero)')
        extended = {name: _state(_bend(w, joints), FINGER_STRAIGHT_BELOW, FINGER_CURLED_ABOVE)
                    for name, joints in FINGERS.items()}
        extended['thumb'] = _state(_bend(w, THUMB), THUMB_STRAIGHT_BELOW, THUMB_CURLED_ABOVE)
        tips = distance(w[THUMB[3]], w[INDEX[3]])
        return HandFeatures(palm_size=palm, extended=extended, pinch=tips / palm_m,
                            palm_center=(cx, cy), thumb_direction=thumb_direction,
                            touching=tips < PINCH_TOUCH_M, three_d=True)

    wrist = pts[WRIST]
    extended = {}
    for name, (_base, middle, _, tip) in FINGERS.items():
        extended[name] = distance(pts[tip], wrist) > distance(pts[middle], wrist) * EXTENDED_RATIO
    extended['thumb'] = distance(pts[THUMB[3]], pts[INDEX[0]]) / palm > THUMB_EXTENDED
    pinch = distance(pts[THUMB[3]], pts[INDEX[3]]) / palm
    return HandFeatures(palm_size=palm, extended=extended, pinch=pinch, palm_center=(cx, cy),
                        thumb_direction=thumb_direction, touching=pinch < PINCH_CLOSE)


def classify(f):
    """Name the static pose of a hand from its features (see ``POSES``).

    Strict by design: a pose is named only when every finger it depends on is
    clearly straight or clearly curled. Otherwise the answer is 'unknown'.
    """
    e = f.extended
    fingers = (e['index'], e['middle'], e['ring'], e['pinky'])
    others = (e['middle'], e['ring'], e['pinky'])
    if f.touching and e['index'] is not None and not all(v is False for v in fingers):
        # Thumb and index tips touching (and not just a fist): OK sign or pinch.
        if all(v is True for v in others):
            return 'ok'
        return 'pinch'
    if None in fingers:
        return 'unknown'
    count = sum(fingers)
    if count == 4:
        return 'open_palm' if e['thumb'] is True else 'unknown'
    if count == 0:
        if e['thumb'] is True and f.thumb_direction > 0.45:
            return 'thumbs_up'
        if e['thumb'] is True and f.thumb_direction < -0.45:
            return 'thumbs_down'
        return 'fist' if e['thumb'] is False else 'unknown'
    if fingers == (True, False, False, False):
        return 'point'
    if fingers == (True, True, False, False):
        return 'victory'
    if fingers == (True, True, True, False):
        return 'three'
    if fingers == (True, False, False, True):
        return 'rock'
    return 'unknown'


def pose_of(landmarks, world=None):
    return classify(features(landmarks, world))
