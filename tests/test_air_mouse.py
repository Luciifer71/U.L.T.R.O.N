"""Air mouse (G2): pure pointer logic, the daemon's safety gate, and wiring."""
import asyncio
from types import SimpleNamespace

import pytest

from ultron.control.pointer_input import MAX_COMMANDS_PER_SEC, PointerController, parse_command
from ultron.gestures import config as gesture_config
from ultron.gestures.pointer import (
    ACTIONS, DOUBLE_TAP_SEC, SLOP, AirMouse, PinchDetector, enabled_actions, to_desktop,
)

FPS = 30
OPEN, TOUCH = 0.9, 0.2


def hand(x=0.5, y=0.45, pose='point', pinch=OPEN, engaged=True, pinch_2d=None, near=None):
    points = [[x, y, 0.0] for _ in range(21)]
    return SimpleNamespace(pose=pose, pinch=pinch, engaged=engaged, near=engaged if near is None else near,
                           landmarks=points, pinch_2d=pinch_2d)


def run(mouse, frames, start=0.0):
    """frames: list of hand states (or None), one per camera frame. Returns commands and actions."""
    commands, actions, now = [], [], start
    for state in frames:
        now += 1 / FPS
        c, e = mouse.update(state, now)
        commands += c
        actions += [x['action'] for x in e]
    return commands, actions, now


def ops(commands):
    return [c['op'] for c in commands]


def tap(pose='point', frames=4, x=0.5):
    return [hand(x=x, pose=pose)] * 4 + [hand(x=x, pose=pose, pinch=TOUCH)] * frames + [hand(x=x, pose=pose)] * 6


# ---- moving ------------------------------------------------------------------

def test_the_hand_moves_the_pointer_across_the_whole_desktop():
    assert to_desktop(0.18, 0.15) == (0.0, 0.0)
    assert to_desktop(0.82, 0.75) == (1.0, 1.0)
    assert to_desktop(0.0, 1.0) == (0.0, 1.0), 'outside the area clamps to the desktop edge'
    commands, _ = AirMouse().update(hand(x=0.5, y=0.45), 0.0)
    assert commands == [{'op': 'move', 'x': 0.5, 'y': 0.5}]


@pytest.mark.parametrize('pose', ['point', 'pinch', 'unknown', 'open_palm', 'three', 'ok'])
def test_any_relaxed_hand_moves_the_pointer(pose):
    """Regression: only a strict 'point' pose moved it, so turned or relaxed hands did nothing."""
    commands, _, _ = run(AirMouse(), [hand(x=0.4 + i * 0.01, pose=pose) for i in range(5)])
    assert ops(commands).count('move') == 5


def test_a_fist_is_a_clutch_that_holds_the_pointer():
    mouse = AirMouse()
    _, _, now = run(mouse, [hand(x=0.5)] * 3)
    commands, _, _ = run(mouse, [hand(x=0.5 + i * 0.02, pose='fist') for i in range(10)], start=now)
    assert commands == []


def test_tiny_jitter_does_not_move_the_pointer():
    commands, _, _ = run(AirMouse(), [hand(x=0.5 + (0.0003 if i % 2 else 0)) for i in range(30)])
    assert ops(commands).count('move') == 1, 'only the first position; jitter is inside the dead zone'


def test_far_or_lost_hands_never_move_it():
    mouse = AirMouse()
    for state in (hand(engaged=False), None):
        commands, _, _ = run(mouse, [state] * 5)
        assert commands == []


def test_a_hand_partly_outside_the_picture_still_works_if_its_tips_are_visible():
    state = hand(engaged=False, near=True)  # pose recognition needs the whole hand, the pointer does not
    commands, _, _ = run(AirMouse(), [state] * 3)
    assert 'move' in ops(commands)


# ---- clicking ----------------------------------------------------------------

@pytest.mark.parametrize('pose', ['point', 'unknown', 'open_palm', 'pinch', 'ok'])
def test_a_pinch_clicks_whatever_the_other_fingers_do(pose):
    """Regression: pinches were missed unless the hand was first recognised as 'point'."""
    commands, actions, _ = run(AirMouse(), tap(pose=pose))
    assert ops(commands).count('down') == 1 and ops(commands).count('up') == 1
    assert actions == ['click']


@pytest.mark.parametrize('frames', [2, 6, 12, 17])
def test_slow_or_quick_taps_are_still_clicks(frames):
    """Regression: a pinch longer than 0.32 s became a drag and broke clicks."""
    commands, actions, _ = run(AirMouse(), tap(frames=frames))
    assert actions == ['click']
    down, up = ops(commands).index('down'), ops(commands).index('up')
    assert 'move' not in ops(commands)[down:up], 'the pointer stays locked while pressed'


def test_the_press_lands_where_you_aimed_before_the_pinch_nudged_the_hand():
    mouse = AirMouse()
    _, _, now = run(mouse, [hand(x=0.5)] * 10)
    aimed = mouse.position
    # Closing a pinch drags the knuckle a little before the pinch registers.
    commands, _, _ = run(mouse, [hand(x=0.505), hand(x=0.51), hand(x=0.512, pinch=TOUCH)], start=now)
    press = ops(commands).index('down')
    assert commands[press - 1]['op'] == 'move'
    assert abs(commands[press - 1]['x'] - aimed[0]) < abs(to_desktop(0.512, 0.45)[0] - aimed[0])


def test_two_quick_taps_land_on_exactly_the_same_spot():
    """Regression: hand drift between taps broke Windows' double-click (4 px window)."""
    mouse = AirMouse()
    commands, actions, _ = run(mouse, tap(x=0.5) + tap(x=0.503))
    presses = [commands[i - 1] for i, c in enumerate(commands) if c['op'] == 'down']
    assert len(presses) == 2 and presses[0] == presses[1]
    assert actions == ['click', 'double_click']


def test_taps_far_apart_are_two_single_clicks():
    mouse = AirMouse()
    _, _, now = run(mouse, tap())
    _, actions, _ = run(mouse, [hand()] * int(FPS * (DOUBLE_TAP_SEC + 0.3)) + tap(), start=now)
    assert actions == ['click']


def test_a_half_closed_hand_neither_clicks_nor_flickers():
    detector = PinchDetector()
    press, release = detector.thresholds()
    changes = [detector.update((press + release) / 2 + (0.01 if i % 2 else -0.01)) for i in range(40)]
    assert changes.count('press') == 0


def test_noise_around_the_threshold_does_not_chatter():
    detector = PinchDetector()
    press, release = detector.thresholds()
    detector.update(TOUCH)
    changes = [detector.update(press + (0.02 if i % 2 else -0.02)) for i in range(40)]
    assert changes.count('release') == 0, 'hysteresis keeps the button down'


# ---- adapting to the user ----------------------------------------------------

def test_a_user_whose_touching_measures_high_is_learned():
    """Hands and cameras differ: one person's touching tips measure about 0.31, not 0.2."""
    detector = PinchDetector()
    assert detector.update(0.315) is None, 'just above the default threshold at first'
    # A clearer pinch now and then teaches the detector how close this user gets.
    for _ in range(4):
        assert detector.update(0.27) == 'press'
        assert detector.update(0.9) is None, 'one open frame is not enough'
        assert detector.update(0.9) == 'release'
    assert detector.update(0.315) == 'press', 'their normal pinch now registers'


def test_a_fist_never_clicks_however_the_detector_has_learned():
    """A fist reads about 0.36 (thumb over the index): it must never press."""
    for learned in (0.05, 0.22, 0.35):
        detector = PinchDetector(touch=learned)
        assert detector.update(0.36) is None
        assert detector.update(0.36, distance_2d=0.05) is None, 'even with tips together in the picture'


def test_learning_stays_within_safe_bounds():
    detector = PinchDetector()
    for closest in [0.01] * 30 + [0.4] * 30:
        detector.update(closest)
        detector.update(1.5)
        press, release = detector.thresholds()
        assert 0.24 <= press <= 0.33 and release == press + 0.10


def test_a_strong_2d_cue_helps_when_3d_reads_a_little_high():
    detector = PinchDetector()
    press, _ = detector.thresholds()
    assert detector.update(press + 0.02, distance_2d=0.08) == 'press'
    assert PinchDetector().update(press + 0.02) is None, 'not without the 2D cue'
    assert PinchDetector().update(press + 0.02, distance_2d=0.4) is None


# ---- dragging ----------------------------------------------------------------

def test_holding_a_pinch_and_moving_drags_and_opening_drops():
    mouse = AirMouse()
    frames = [hand()] * 4 + [hand(x=0.5 + i * 0.006, pinch=TOUCH) for i in range(20)] + [hand(x=0.62)] * 3
    commands, actions, _ = run(mouse, frames)
    o = ops(commands)
    assert o.count('down') == 1 and o.count('up') == 1
    assert 'move' in o[o.index('down') + 1:o.index('up')], 'the pointer follows once the hand clearly moves'
    assert actions == ['drag_start', 'drag_end']


def test_small_wobble_while_pressed_is_not_a_drag():
    frames = [hand()] * 4 + [hand(x=0.5 + (SLOP * 0.3 if i % 2 else 0), pinch=TOUCH) for i in range(15)] + [hand()] * 3
    _, actions, _ = run(AirMouse(), frames)
    assert actions == ['click']


@pytest.mark.parametrize('lost', [None, hand(engaged=False)])
def test_losing_the_hand_mid_press_releases_after_a_short_grace(lost):
    commands, _, _ = run(AirMouse(), [hand()] * 3 + [hand(pinch=TOUCH)] * 8 + [lost] * 10)
    assert ops(commands).count('down') == 1 and ops(commands)[-1] == 'up'


def test_a_fist_mid_press_releases_at_once():
    commands, _, _ = run(AirMouse(), [hand()] * 3 + [hand(pinch=TOUCH)] * 8 + [hand(pose='fist', pinch=TOUCH)])
    assert ops(commands).count('down') == 1 and ops(commands)[-1] == 'up'


def test_ending_gesture_mode_releases_the_button():
    mouse = AirMouse()
    run(mouse, [hand()] * 3 + [hand(pinch=TOUCH)] * 8)
    commands, _ = mouse.reset()
    assert commands == [{'op': 'up'}]
    assert mouse.reset() == ([], [])


# ---- scrolling ---------------------------------------------------------------

def test_victory_sign_moved_up_scrolls_up_and_down_scrolls_down():
    mouse = AirMouse()
    commands, _, now = run(mouse, [hand(pose='victory', y=0.6 - i * 0.01) for i in range(15)])
    deltas = [c['delta'] for c in commands if c['op'] == 'scroll']
    assert deltas and all(d > 0 for d in deltas)
    assert 'move' not in ops(commands), 'scrolling does not move the pointer'
    commands, _, _ = run(mouse, [hand(pose='victory', y=0.45 + i * 0.01) for i in range(15)], start=now)
    assert all(c['delta'] < 0 for c in commands if c['op'] == 'scroll')


# ---- configuration -----------------------------------------------------------

def test_only_actions_mapped_in_a_live_stage_are_enabled():
    config = gesture_config.load()
    assert 'G2' in gesture_config.LIVE_STAGES
    assert enabled_actions(config, gesture_config.LIVE_STAGES) == frozenset(ACTIONS)
    assert enabled_actions(config, ('G1',)) == frozenset()


def test_disabled_actions_do_nothing():
    mouse = AirMouse(enabled=frozenset({'pointer.move'}))
    frames = tap() + [hand(pinch=TOUCH)] * 20 + [hand(pose='victory', y=0.3 + i * 0.02) for i in range(10)]
    commands, actions, _ = run(mouse, frames)
    assert set(ops(commands)) <= {'move'} and actions == []


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
    assert all(r.capability == 'pointer.button' for r in audit.records)


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
    right = hand()
    right.side = 'Right'
    service.tracker.hands = {'Right': right}
    asyncio.run(service.step())
    right.pinch = TOUCH
    for _ in range(4):
        asyncio.run(service.step())
    pointer = [p['op'] for s, p in recorder.raw if s == 'ultron.pointer']
    assert 'down' in pointer
    service.control('gesture_off', 'ops')
    pointer = [p['op'] for s, p in recorder.raw if s == 'ultron.pointer']
    assert pointer[-1] == 'up', 'leaving gesture mode releases the button'


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


# ---- recordings ----------------------------------------------------------------

def test_recordings_hold_landmarks_only_and_replay_the_same_clicks(tmp_path):
    import json
    from ultron.gestures import recording

    recorder = recording.GestureRecorder(tmp_path, clock=lambda: 0)
    frames = tap() + tap()
    now = 0.0
    for state in frames:
        now += 1 / FPS
        state = SimpleNamespace(**vars(state), side='Right')
        recorder.write(now, [state], [])
    recorder.close()
    rows = [json.loads(line) for line in recorder.path.read_text().splitlines()]
    assert len(rows) == len(frames)
    assert set(rows[0]['hands'][0]) == {'side', 'pose', 'engaged', 'near', 'pinch', 'pinch_2d', 'points'}
    events, pinches = recording.replay(recorder.path)
    assert [action for _, action in events] == ['click', 'double_click']
    assert min(pinches) == TOUCH


def test_recording_stops_by_itself(tmp_path, monkeypatch):
    from ultron.gestures import recording
    monkeypatch.setattr(recording, 'MAX_FRAMES', 3)
    recorder = recording.GestureRecorder(tmp_path, clock=lambda: 0)
    state = SimpleNamespace(**vars(hand()), side='Right')
    for i in range(10):
        recorder.write(i, [state], [])
    assert len(recorder.path.read_text().splitlines()) == 3


def test_recording_is_off_unless_asked(monkeypatch):
    pytest.importorskip('numpy')
    from ultron.agents import vision_service
    monkeypatch.delenv('ULTRON_GESTURE_RECORD', raising=False)
    assert vision_service.gesture_recorder() is None



# ---- robustness under real-world noise --------------------------------------------

def test_one_bad_frame_never_turns_a_click_into_two():
    for glitch in (hand(pinch=0.9), None, hand(engaged=False)):  # a spike, a dropped hand, a bad estimate
        frames = [hand()] * 4 + [hand(pinch=TOUCH)] * 3 + [glitch] + [hand(pinch=TOUCH)] * 3 + [hand()] * 6
        commands, actions, _ = run(AirMouse(), frames)
        assert ops(commands).count('down') == 1 and ops(commands).count('up') == 1, glitch
        assert actions == ['click']


@pytest.mark.parametrize('seed', range(5))
def test_many_noisy_taps_give_exactly_the_right_clicks(seed):
    """Hundreds of taps with jitter, noisy pinch estimates, spikes and dropped frames."""
    import random
    rng = random.Random(seed)
    mouse, frames, taps = AirMouse(), [], 0
    for _ in range(60):
        x, y = rng.uniform(0.3, 0.7), rng.uniform(0.3, 0.6)
        def noisy(pinch):
            if rng.random() < 0.04:
                return None  # dropped frame
            value = pinch + rng.gauss(0, 0.03)
            if rng.random() < 0.03:
                value += rng.choice([0.25, -0.1])  # a bad estimate
            return hand(x=x + rng.gauss(0, 0.002), y=y + rng.gauss(0, 0.002), pinch=value,
                        pose=rng.choice(['point', 'unknown', 'pinch', 'open_palm']))
        frames += [noisy(rng.uniform(0.75, 0.95)) for _ in range(rng.randint(6, 12))]
        frames += [noisy(rng.uniform(0.15, 0.24)) for _ in range(rng.randint(3, 14))]
        frames += [noisy(rng.uniform(0.75, 0.95)) for _ in range(rng.randint(14, 24))]  # pauses longer than a double-click
        taps += 1
    commands, actions, _ = run(mouse, frames)
    assert ops(commands).count('down') == taps == ops(commands).count('up')
    assert actions.count('click') + actions.count('double_click') == taps
