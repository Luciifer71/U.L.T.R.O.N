"""Gesture mapping configuration (``config/gestures.json``).

The file is the single source of truth for which gesture does what; the table in
``docs/gestures.md`` is checked against it by the tests. Validation is strict so
a typo can never silently map a gesture to an unintended action.
"""
from dataclasses import dataclass
import json
from pathlib import Path

GESTURES = frozenset({
    'point', 'pinch_tap', 'double_pinch', 'pinch_hold', 'two_finger_scroll',
    'grab_move', 'grab_throw', 'two_hand_stretch', 'grab_release',
    'swipe_left', 'swipe_right', 'twist', 'palm_hold', 'frame', 'fist_hold',
    'both_palms', 'both_palms_push',
})

ACTIONS = frozenset({
    'pointer.move', 'pointer.click', 'pointer.double_click', 'pointer.drag', 'pointer.scroll',
    'window.move', 'window.throw', 'window.resize', 'clipboard.copy_paste',
    'media.previous', 'media.next', 'media.play_pause', 'volume.adjust',
    'screen.screenshot', 'system.lock', 'system.stop', 'gesture.exit',
})

# Actions that change something important must always ask first.
MUST_CONFIRM = frozenset({'system.lock'})
STAGES = ('G1', 'G2', 'G3', 'G4', 'G5', 'G6')
HANDS = ('dominant', 'other', 'both')


@dataclass(frozen=True)
class Mapping:
    gesture: str
    hands: str
    action: str
    stage: str
    description: str
    confirm: bool = False


@dataclass(frozen=True)
class GestureConfig:
    dominant_hand: str
    mappings: tuple

    def for_gesture(self, gesture):
        return next((m for m in self.mappings if m.gesture == gesture), None)


def default_path():
    from ultron.paths import project_root
    return project_root() / 'config' / 'gestures.json'


def parse(data):
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('gestures.json: expected {"version": 1, ...}')
    dominant = data.get('dominant_hand', 'Right')
    if dominant not in ('Right', 'Left'):
        raise ValueError('gestures.json: dominant_hand must be "Right" or "Left"')
    mappings, seen = [], set()
    for i, row in enumerate(data.get('mappings') or []):
        where = f'gestures.json mapping {i + 1}'
        if not isinstance(row, dict):
            raise ValueError(f'{where}: must be an object')
        gesture, action = row.get('gesture'), row.get('action')
        if gesture not in GESTURES:
            raise ValueError(f'{where}: unknown gesture {gesture!r}')
        if action not in ACTIONS:
            raise ValueError(f'{where}: unknown action {action!r}')
        if gesture in seen:
            raise ValueError(f'{where}: gesture {gesture!r} is mapped twice')
        seen.add(gesture)
        hands = row.get('hands', 'dominant')
        if hands not in HANDS:
            raise ValueError(f'{where}: hands must be one of {HANDS}')
        stage = row.get('stage', 'G1')
        if stage not in STAGES:
            raise ValueError(f'{where}: stage must be one of {STAGES}')
        confirm = bool(row.get('confirm', False)) or action in MUST_CONFIRM
        description = str(row.get('description', '')).strip()
        if not description:
            raise ValueError(f'{where}: description is required')
        mappings.append(Mapping(gesture, hands, action, stage, description, confirm))
    return GestureConfig(dominant, tuple(mappings))


def load(path=None):
    return parse(json.loads(Path(path or default_path()).read_text(encoding='utf-8')))
