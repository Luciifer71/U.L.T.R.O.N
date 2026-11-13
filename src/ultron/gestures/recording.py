"""Opt-in gesture recordings for tuning from real use (no images, ever).

With ``ULTRON_GESTURE_RECORD=1`` the vision service writes one JSON line per
camera frame to ``runtime/gesture-recordings/<time>.jsonl``: the tracked hands
(21 landmark coordinates, pose, pinch distances) and any air-mouse events.
Nothing else, and never a picture. A recording replays deterministically
through the same air-mouse logic (``run_ultron.py gesture-replay <file>``), so
a missed pinch can be found and fixed from real data.
"""
from __future__ import annotations

import json
from pathlib import Path
import time
from types import SimpleNamespace

from ultron.gestures.pointer import AirMouse

MAX_FRAMES = 30 * 60 * 10  # ten minutes at 30 fps, then recording stops


class GestureRecorder:
    def __init__(self, folder: Path, clock=time.time):
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / time.strftime('%Y%m%d-%H%M%S.jsonl', time.localtime(clock()))
        self._file = self.path.open('a', encoding='utf-8')
        self.frames = 0

    def write(self, now, hands, events):
        if self._file is None:
            return
        rows = [{'side': h.side, 'pose': h.pose, 'engaged': h.engaged, 'near': h.near,
                 'pinch': _number(h.pinch), 'pinch_2d': _number(getattr(h, 'pinch_2d', None)),
                 'points': [[round(v, 4) for v in p] for p in h.landmarks]} for h in hands]
        self._file.write(json.dumps({'t': round(now, 4), 'hands': rows, 'events': events}) + '\n')
        self.frames += 1
        if self.frames >= MAX_FRAMES:
            self.close()

    def close(self):
        if self._file is not None:
            self._file.close()
            self._file = None


def _number(value):
    return round(value, 4) if isinstance(value, (int, float)) else None


def frames(path):
    """(time, {side: hand}) for each recorded frame."""
    with Path(path).open(encoding='utf-8') as handle:
        for line in handle:
            row = json.loads(line)
            hands = {h['side']: SimpleNamespace(**{**h, 'landmarks': h['points']}) for h in row['hands']}
            yield row['t'], hands


def replay(path, dominant='Right'):
    """Run a recording through the air mouse. Returns events and pinch statistics."""
    mouse, events, pinches = AirMouse(), [], []
    for now, hands in frames(path):
        hand = hands.get(dominant)
        if hand is not None:
            pinches.append(hand.pinch)
        _, new = mouse.update(hand, now)
        events += [(round(now, 3), e['action']) for e in new]
    return events, pinches


def main(argv=None):
    import sys
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print('Usage: run_ultron.py gesture-replay <recording.jsonl> [Right|Left]')
        return 2
    events, pinches = replay(args[0], args[1] if len(args) > 1 else 'Right')
    for when, action in events:
        print(f'{when:9.3f}s  {action}')
    if pinches:
        ordered = sorted(pinches)
        print(f'{len(pinches)} frames with the hand; pinch distance min {ordered[0]:.3f}, '
              f'10% {ordered[len(ordered) // 10]:.3f}, median {ordered[len(ordered) // 2]:.3f}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
