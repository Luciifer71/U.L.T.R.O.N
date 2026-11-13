"""Air mouse (G2): pure pointer logic, the daemon's safety gate, and wiring."""
import asyncio
from types import SimpleNamespace

import pytest

from ultron.control.pointer_input import MAX_COMMANDS_PER_SEC, PointerController, parse_command
from ultron.gestures import config as gesture_config
from ultron.gestures.pointer import (
    ACTIONS, DOUBLE_TAP_SEC, PINCH_PRESS, PINCH_RELEASE, TAP_MAX_SEC, AirMouse, enabled_actions, to_desktop,
)

FPS = 30


def hand(x=0.5, y=0.45, pose='point', pinch=0.9, engaged=True):
    points = [[x, y, 0.0] for _ in range(21)]
    return SimpleNamespace(pose=pose, pinch=pinch, engaged=engaged, landmarks=points)


def run(mouse, frames, start=0.0):
    """frames: list of hand states (or None), one per camera frame. Returns ops and actions."""
    ops, actions, now = [], [], start
    for state in frames:
        now += 1 / FPS
        commands, events = mouse.update(state, now)
        ops += [c['op'] for c in commands]
        actions += [e['action'] for e in events]
    return ops, actions, now


# ---- moving ------------------------------------------------------------------

def test_pointing_moves_the_pointer_across_the_whole_desktop():
    assert to_desktop(0.18, 0.15) == (0.0, 0.0)
    assert to_desktop(0.82, 0.75) == (1.0, 1.0)
    assert to_desktop(0.0, 1.0) == (0.0, 1.0), 'outside the area clamps to the desktop edge'
    mouse = AirMouse()
    commands, _ = mouse.update(hand(x=0.5, y=0.45), 0.0)
    assert commands == [{'op': 'move', 'x': 0.5, 'y': 0.5}]


def test_tiny_jitter_does_not_move_the_pointer():
    mouse = AirMouse()
    ops, _, _ = run(mouse, [hand(x=0.5 + (0.0003 if i % 2 else 0), y=0.45) for i in range(30)])
    assert ops.count('move') == 1, 'only the first position; jitter is inside the dead zone'


def test_other_poses_and_disengaged_hands_never_move_it():
    mouse = AirMouse()
    for state in (hand(pose='open_palm'), hand(pose='fist'), hand(engaged=False), None):
        ops, _, _ = run(mouse, [state] * 5)
        assert ops == []


# ---- clicking ----------------------------------------------------------------

def tap_frames(press_frames=4):
    return [hand()] * 3 + [hand(pinch=0.2, pose='pinch')] * press_frames + [hand(pinch=0.6)] * 3


def test_a_quick_pinch_clicks_once_without_moving_the_pointer():
    mouse = AirMouse()
    _, _, now = run(mouse, [hand()] * 3)
    moving_hand = [hand(x=0.5 + i * 0.01, pinch=0.2, pose='pinch') for i in range(4)]  # hand drifts while pinching
    ops, actions, _ = run(mouse, moving_hand + [hand(pinch=0.6)], start=now)
    assert ops.count('click') == 1 and 'down' not in ops
    assert 'move' not in ops[:ops.index('click')], 'the pointer is frozen until the click'
    assert actions == ['click']


def test_two_quick_taps_are_a_double_click():
    mouse = AirMouse()
    ops, actions, _ = run(mouse, tap_frames() + tap_frames())
    assert ops.count('click') == 2
    assert actions == ['click', 'double_click']


def test_taps_far_apart_are_two_single_clicks():
    mouse = AirMouse()
    _, _, now = run(mouse, tap_frames())
    _, actions, _ = run(mouse, [hand()] * int(FPS * (DOUBLE_TAP_SEC + 0.3)) + tap_frames(), start=now)
    assert actions == ['click']


def test_pinch_hysteresis_ignores_a_half_closed_hand():
    mouse = AirMouse()
    between = (PINCH_PRESS + PINCH_RELEASE) / 2
    ops, actions, _ = run(mouse, [hand(pinch=between)] * 20)
    assert 'click' not in ops and actions == []


# ---- dragging ----------------------------------------------------------------

def test_holding_a_pinch_drags_and_opening_it_drops():
    mouse = AirMouse()
    hold = int(FPS * TAP_MAX_SEC) + 3
    frames = [hand()] * 3 + [hand(x=0.5 + i * 0.005, pinch=0.2, pose='pinch') for i in range(hold + 10)] + [hand(pinch=0.6)]
    ops, actions, _ = run(mouse, frames)
    assert ops.count('down') == 1 and ops.count('up') == 1 and 'click' not in ops
    assert 'move' in ops[ops.index('down'):ops.index('up')], 'the pointer moves while dragging'
    assert actions == ['drag_start', 'drag_end']


@pytest.mark.parametrize('lost', [None, hand(engaged=False), hand(pose='fist', pinch=0.6)])
def test_losing_the_hand_mid_drag_always_releases_the_button(lost):
    mouse = AirMouse()
    hold = int(FPS * TAP_MAX_SEC) + 3
    ops, _, _ = run(mouse, [hand()] * 2 + [hand(pinch=0.2, pose='pinch')] * hold + [lost])
    assert ops.count('down') == 1 and ops[-1] == 'up'


def test_ending_gesture_mode_releases_the_button():
    mouse = AirMouse()
    run(mouse, [hand()] * 2 + [hand(pinch=0.2, pose='pinch')] * (int(FPS * TAP_MAX_SEC) + 3))
    commands, events = mouse.reset()
    assert commands == [{'op': 'up'}] and events[0]['action'] == 'drag_end'
    assert mouse.reset() == ([], [])


# ---- scrolling ---------------------------------------------------------------

def test_victory_sign_moved_up_scrolls_up_and_down_scrolls_down():
    mouse = AirMouse()
    up = [hand(pose='victory', y=0.6 - i * 0.01) for i in range(15)]
    commands = []
    now = 0.0
    for state in up:
        now += 1 / FPS
        commands += mouse.update(state, now)[0]
    deltas = [c['delta'] for c in commands if c['op'] == 'scroll']
    assert deltas and all(d > 0 for d in deltas)
    assert not [c for c in commands if c['op'] == 'move'], 'scrolling does not move the pointer'
    down = [hand(pose='victory', y=0.45 + i * 0.01) for i in range(15)]
    commands = []
    for state in down:
        now += 1 / FPS
        commands += mouse.update(state, now)[0]
    assert all(c['delta'] < 0 for c in commands if c['op'] == 'scroll')


# ---- configuration -----------------------------------------------------------

def test_only_actions_mapped_in_a_live_stage_are_enabled():
    config = gesture_config.load()
    assert 'G2' in gesture_config.LIVE_STAGES
    assert enabled_actions(config, gesture_config.LIVE_STAGES) == frozenset(ACTIONS)
    assert enabled_actions(config, ('G1',)) == frozenset()


def test_disabled_actions_do_nothing():
    mouse = AirMouse(enabled=frozenset({'pointer.move'}))
    ops, actions, _ = run(mouse, tap_frames() + [hand(pinch=0.2, pose='pinch')] * 20 + [hand(pose='victory', y=0.3 + i * 0.02) for i in range(10)])
    assert set(ops) <= {'move'} and actions == []


# ---- the daemon side ---------------------------------------------------------

class FakeMouse:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *args: self.calls.append((name, *args))


class FakeAudit:
    def __init__(self):
        self.records = []

    def record(self, record):
        self.records.append(record)


def controller(clock=lambda: 0.0):
    mouse, audit = FakeMouse(), FakeAudit()
    return PointerController(mouse, audit=audit, clock=clock), mouse, audit


@pytest.mark.parametrize('payload', [
    None, 'click', {}, {'op': 'format'}, {'op': 'move', 'x': 'left', 'y': 0}, {'op': 'move', 'x': float('nan'), 'y': 0},
    {'op': 'move', 'x': True, 'y': 0}, {'op': 'scroll', 'delta': 0}, {'op': 'scroll', 'delta': 99999},
    {'op': 'scroll', 'delta': 1.5},
])
def test_malformed_commands_are_refused(payload):
    assert parse_command(payload) is None


def test_moves_are_clamped_to_the_desktop():
    assert parse_command({'op': 'move', 'x': -2, 'y': 7}) == {'op': 'move', 'x': 0.0, 'y': 1.0}


def test_nothing_reaches_the_mouse_unless_gesture_mode_is_on():
    pointer, mouse, _ = controller()
    assert not pointer.handle({'op': 'click'})
    pointer.vision_state({'gesture': True})
    assert pointer.handle({'op': 'click'})
    pointer.vision_state({'gesture': False})
    assert not pointer.handle({'op': 'move', 'x': 0.5, 'y': 0.5})
    assert mouse.calls == [('click',)]


def test_gesture_mode_ending_releases_a_held_button_and_audits_it():
    pointer, mouse, audit = controller()
    pointer.vision_state({'gesture': True})
    pointer.handle({'op': 'down'})
    assert not pointer.handle({'op': 'down'}), 'never pressed twice'
    pointer.vision_state({'gesture': False})
    assert mouse.calls == [('down',), ('up',)]
    assert [r.operation for r in audit.records] == ['down', 'up']
    assert all(r.capability == 'pointer.drag' for r in audit.records)


def test_clicks_and_scrolls_are_audited_but_moves_are_not():
    pointer, _, audit = controller()
    pointer.vision_state({'gesture': True})
    pointer.handle({'op': 'move', 'x': 0.2, 'y': 0.3})
    pointer.handle({'op': 'click'})
    pointer.handle({'op': 'scroll', 'delta': 240})
    assert [(r.capability, r.operation) for r in audit.records] == [('pointer.click', 'click'), ('pointer.scroll', 'scroll')]
    assert audit.records[1].metadata == {'source': 'air_mouse', 'delta': 240}


def test_a_flood_of_commands_is_rate_limited():
    pointer, mouse, _ = controller()
    pointer.vision_state({'gesture': True})
    accepted = sum(pointer.handle({'op': 'move', 'x': 0.5, 'y': 0.5}) for _ in range(MAX_COMMANDS_PER_SEC * 3))
    assert accepted == MAX_COMMANDS_PER_SEC


def test_without_a_mouse_backend_nothing_happens():
    pointer = PointerController(None, audit=FakeAudit())
    pointer.vision_state({'gesture': True})
    assert not pointer.handle({'op': 'click'})


# ---- wiring in the vision service ---------------------------------------------

def test_vision_service_sends_pointer_commands_and_releases_on_exit():
    pytest.importorskip('numpy')
    from ultron.agents import vision_service

    class Recorder:
        def __init__(self):
            self.signals, self.raw = [], []

        def emit(self, kind, payload):
            self.signals.append((kind, payload))

        def emit_raw(self, subject, payload):
            self.raw.append((subject, payload))

    class Camera:
        def read(self):
            import numpy as np
            return True, np.zeros((720, 1280, 3), dtype=np.uint8)

        def release(self):
            pass

    recorder = Recorder()
    clock = [0.0]

    def tick():
        clock[0] += 1 / FPS
        return clock[0]
    service = vision_service.VisionService(
        recorder, open_camera=lambda w, h: Camera(),
        make_hands=lambda: SimpleNamespace(detect=lambda frame, now: [], close=lambda: None),
        make_faces=lambda: (lambda frame: []), clock=tick, config=gesture_config.load())
    assert service.air_mouse is not None
    service.control('gesture_on', 'ops')
    # Put a pinching right hand in the tracker directly (the tracker is tested elsewhere).
    service.tracker.update = lambda detections, now: []
    right = hand(pinch=0.2, pose='pinch')
    right.side = 'Right'
    service.tracker.hands = {'Right': right}
    for _ in range(int(FPS * TAP_MAX_SEC) + 4):
        asyncio.run(service.step())
    pointer = [p['op'] for s, p in recorder.raw if s == 'ultron.pointer']
    assert 'down' in pointer
    service.control('gesture_off', 'ops')
    pointer = [p['op'] for s, p in recorder.raw if s == 'ultron.pointer']
    assert pointer[-1] == 'up', 'leaving gesture mode releases the button'
    actions = [p.get('action') for k, p in recorder.signals if k == 'gesture' and p.get('type') == 'pointer']
    assert 'drag_start' in actions


def test_air_mouse_can_be_switched_off():
    pytest.importorskip('numpy')
    from ultron.agents import vision_service
    service = vision_service.VisionService(
        SimpleNamespace(emit=lambda *a: None, emit_raw=lambda *a: None), open_camera=None, make_hands=None,
        make_faces=None, config=gesture_config.load(), air_mouse=False)
    assert service.air_mouse is None


def test_windows_input_structure_has_the_size_sendinput_expects():
    """Regression guard: a wrongly sized INPUT makes SendInput ignore every event."""
    import ctypes
    from ultron.control.pointer_input import WindowsMouse
    sent = []

    def send(count, pointer, size):
        event = ctypes.cast(pointer, ctypes.POINTER(mouse._INPUT)).contents
        sent.append((count, size, event.type, event.mi.dx, event.mi.dy, event.mi.mouseData, event.mi.dwFlags))
        return 1
    mouse = WindowsMouse(send=send)
    expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
    assert ctypes.sizeof(mouse._INPUT) == expected
    mouse.move(0.5, 1.0)
    mouse.scroll(-240)
    mouse.click()
    assert sent[0][:5] == (1, expected, 0, 32768, 65535)
    assert sent[0][6] == WindowsMouse.MOVE | WindowsMouse.ABSOLUTE | WindowsMouse.VIRTUALDESK
    assert sent[1][5] == (-240) & 0xFFFFFFFF and sent[1][6] == WindowsMouse.WHEEL
    assert [e[6] for e in sent[2:]] == [WindowsMouse.LEFTDOWN, WindowsMouse.LEFTUP]
