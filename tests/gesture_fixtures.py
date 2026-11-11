"""Hand landmark fixtures for gesture tests: real recordings and synthetic hands."""
import json
import math
from pathlib import Path

FIXTURES = Path(__file__).parent / 'fixtures' / 'hands'


def recorded(name):
    """Landmarks MediaPipe produced for a real photo (see the fixture's 'source')."""
    return json.loads((FIXTURES / f'{name}.json').read_text())['landmarks']


def synthetic_hand(extended=('thumb', 'index', 'middle', 'ring', 'pinky'), pinch=False,
                   centre=(0.5, 0.5), size=0.12, thumb='side'):
    """A plausible upright right hand (palm toward camera) built from joint angles.

    ``extended`` fingers point up; the rest curl into the palm. ``pinch`` puts the
    thumb tip on the index tip. ``thumb`` is 'side', 'up' or 'down' for an
    extended thumb. Coordinates are image-normalised (y down).
    """
    cx, cy = centre
    s = size  # wrist to middle-finger base
    wrist = (cx, cy + s * 0.55, 0.0)
    bases = {'index': -0.32, 'middle': -0.1, 'ring': 0.12, 'pinky': 0.32}
    points = [wrist] + [None] * 20
    starts = {'index': 5, 'middle': 9, 'ring': 13, 'pinky': 17}
    for name, dx in bases.items():
        base = (cx + dx * s, cy - s * 0.45, 0.0)
        i = starts[name]
        points[i] = base
        if name in extended:
            for k, frac in enumerate((0.45, 0.75, 1.0), start=1):
                points[i + k] = (base[0], base[1] - frac * s * 0.9, 0.0)
        else:  # curled: middle joint above the base, tip folded back toward the wrist
            points[i + 1] = (base[0], base[1] - 0.25 * s, -0.02)
            points[i + 2] = (base[0], base[1] - 0.05 * s, -0.04)
            points[i + 3] = (base[0], base[1] + 0.15 * s, -0.03)
    # Thumb from the wrist toward the index side.
    t0 = (cx - 0.25 * s, cy + 0.35 * s, 0.0)
    points[1] = t0
    if pinch:
        tip = points[8] if 'index' in extended else (points[5][0], points[5][1] - 0.4 * s, 0.0)
        if 'index' not in extended:
            points[6], points[7], points[8] = ((points[5][0], points[5][1] - 0.2 * s, 0.0),
                                               (points[5][0] - 0.05 * s, points[5][1] - 0.35 * s, 0.0), tip)
        points[2] = (t0[0] - 0.15 * s, t0[1] - 0.25 * s, 0.0)
        points[3] = ((points[2][0] + tip[0]) / 2, (points[2][1] + tip[1]) / 2, 0.0)
        points[4] = (tip[0] + 0.02 * s, tip[1] + 0.02 * s, 0.0)
    elif 'thumb' in extended:
        direction = {'side': (-1.0, -0.2), 'up': (-0.8, -1.0), 'down': (-0.8, 1.0)}[thumb]
        norm = math.hypot(*direction)
        ux, uy = direction[0] / norm, direction[1] / norm
        # A thumbs-up/down thumb sticks out well clear of the fist.
        reach = 1.0 if thumb == 'side' else 1.45
        for k, frac in enumerate((0.35, 0.65, 0.95), start=2):
            points[k] = (t0[0] + ux * frac * reach * s, t0[1] + uy * frac * reach * s, 0.0)
    else:  # thumb tucked across the palm
        points[2] = (t0[0] + 0.1 * s, t0[1] - 0.15 * s, -0.02)
        points[3] = (t0[0] + 0.22 * s, t0[1] - 0.25 * s, -0.03)
        points[4] = (cx - 0.05 * s, cy - 0.05 * s, -0.03)
    return [list(p) for p in points]


def recorded_world(name):
    """MediaPipe's metric 3D landmarks for the same recorded photo."""
    return json.loads((FIXTURES / f'{name}.json').read_text())['world']


def world_of(points, palm_metres=0.09):
    """Synthetic image landmarks as metric 3D landmarks (palm 9 cm, centred on the hand)."""
    palm = math.dist(points[0][:2], points[9][:2])
    k = palm_metres / palm
    cx = sum(p[0] for p in points) / 21
    cy = sum(p[1] for p in points) / 21
    return [[(p[0] - cx) * k, (p[1] - cy) * k, p[2] * k] for p in points]
