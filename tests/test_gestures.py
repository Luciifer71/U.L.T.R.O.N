import asyncio
import math
import random
from types import SimpleNamespace

import pytest

from gesture_fixtures import recorded, recorded_world, synthetic_hand, world_of
from ultron.gestures import config as gesture_config
from ultron.gestures.activation import DoubleClapDetector, gesture_command
from ultron.gestures.filters import OneEuroFilter
from ultron.gestures.hands import features, pose_of
from ultron.gestures.tracker import EXIT_HOLD_SEC, GestureTracker


# ---- poses -----------------------------------------------------------------

@pytest.mark.parametrize('name', ['point', 'thumbs_up', 'victory', 'fist', 'open_palm'])
def test_real_recorded_hands_are_recognised_from_3d_joint_angles(name):
    assert pose_of(recorded(name), recorded_world(name)) == name


def test_3d_angles_read_a_hand_seen_from_the_back_which_2d_could_not():
    # open_palm.json is the back of an open hand: the flat 2D method misses it.
    assert pose_of(recorded('open_palm')) == 'unknown'
    assert pose_of(recorded('open_palm'), recorded_world('open_palm')) == 'open_palm'


def test_a_half_bent_finger_gives_no_pose_instead_of_a_guess():
    hand = synthetic_hand(extended=('index',))
    world = world_of(hand)
    # Bend the middle finger halfway: 40 degrees at its middle joint and 45 more at
    # its end joint (85 in all), neither clearly straight nor clearly curled.
    base = world[9]
    pip = [base[0], base[1] - 0.04, base[2]]

    def step(point, degrees, length):
        a = math.radians(degrees)
        return [point[0], point[1] - length * math.cos(a), point[2] - length * math.sin(a)]
    world[10] = pip
    world[11] = step(pip, 40, 0.025)
    world[12] = step(world[11], 85, 0.02)
    assert features(hand, world).extended['middle'] is None
    assert pose_of(hand, world) == 'unknown'


@pytest.mark.parametrize('kwargs,expected', [
    ({}, 'open_palm'),
    ({'extended': ()}, 'fist'),
    ({'extended': ('index',)}, 'point'),
    ({'extended': ('index', 'middle')}, 'victory'),
    ({'extended': ('index', 'middle', 'ring')}, 'three'),
    ({'extended': ('index', 'pinky')}, 'rock'),
    ({'extended': ('thumb',), 'thumb': 'up'}, 'thumbs_up'),
    ({'extended': ('thumb',), 'thumb': 'down'}, 'thumbs_down'),
    ({'extended': ('index',), 'pinch': True}, 'pinch'),
    ({'extended': ('index', 'middle', 'ring', 'pinky'), 'pinch': True}, 'ok'),
])
def test_synthetic_poses(kwargs, expected):
    hand = synthetic_hand(**kwargs)
    assert pose_of(hand) == expected, '2D fallback'
    assert pose_of(hand, world_of(hand)) == expected, '3D joint angles'


def test_poses_do_not_depend_on_hand_size_or_position():
    for size in (0.06, 0.12, 0.25):
        for centre in ((0.2, 0.3), (0.7, 0.6)):
            assert pose_of(synthetic_hand(extended=('index',), size=size, centre=centre)) == 'point'


def test_bad_landmarks_are_rejected():
    with pytest.raises(ValueError):
        features([[0, 0, 0]] * 20)
    with pytest.raises(ValueError):
        features([[0.5, 0.5, 0]] * 21)


# ---- filter ----------------------------------------------------------------

def test_one_euro_filter_steadies_jitter_but_follows_real_moves():
    f = OneEuroFilter()
    rng = random.Random(1)
    still = [f(0.5 + rng.uniform(-0.01, 0.01), i / 30) for i in range(60)]
    assert max(still[30:]) - min(still[30:]) < 0.01, 'jitter is reduced'
    t = 2.0
    for i in range(15):  # a quick, real move to 0.8
        t += 1 / 30
        value = f(0.8, t)
    assert value > 0.75, 'fast moves are followed without much lag'


# ---- tracker ---------------------------------------------------------------

def frames(tracker, hands, start, count, fps=30):
    events, now = [], start
    for _ in range(count):
        now += 1 / fps
        events += tracker.update(hands, now)
    return events, now


def test_a_pose_needs_several_frames_and_one_bad_frame_changes_nothing():
    tracker = GestureTracker()
    point = [('Right', synthetic_hand(extended=('index',)), 0.9)]
    fist = [('Right', synthetic_hand(extended=()), 0.9)]
    events, now = frames(tracker, point, 0, 2)
    assert events == [], 'two frames are not enough'
    events, now = frames(tracker, point, now, 2)
    assert [e['pose'] for e in events] == ['point']
    events, now = frames(tracker, fist, now, 1)
    events2, now = frames(tracker, point, now, 3)
    assert events == [] and events2 == [], 'a one-frame glitch is ignored'


def test_hands_cut_off_by_the_frame_or_far_away_do_nothing():
    tracker = GestureTracker()
    cut_off = [('Right', synthetic_hand(extended=('index',), centre=(0.5, 0.95)), 0.9)]
    tiny = [('Right', synthetic_hand(extended=('index',), size=0.02), 0.9)]
    for hands in (cut_off, tiny):
        events, _ = frames(tracker, hands, 0, 10)
        assert not [e for e in events if e['pose'] != 'unknown']


@pytest.mark.parametrize('y', [0.2, 0.5, 0.8])
def test_height_in_the_frame_does_not_matter(y):
    """Regression: hands held low (normal with a laptop webcam) were ignored."""
    tracker = GestureTracker()
    events, _ = frames(tracker, [('Right', synthetic_hand(extended=('index',), centre=(0.5, y), size=0.1), 0.9)], 0, 5)
    assert [e['pose'] for e in events] == ['point']


def test_two_hands_with_the_same_label_are_told_apart_by_position():
    """Regression: MediaPipe often calls both palms 'Right'; one hand was dropped."""
    tracker = GestureTracker()
    both_right = [('Right', synthetic_hand(centre=(0.3, 0.5)), 0.9), ('Right', synthetic_hand(centre=(0.7, 0.5)), 0.9)]
    frames(tracker, both_right, 0, 5)
    sides = {h['side']: h['points'][0][0] for h in tracker.snapshot()}
    assert set(sides) == {'Left', 'Right'}
    assert sides['Right'] > sides['Left'], 'the right hand is on the right of the mirrored picture'


def test_both_palms_exit_even_when_both_are_labelled_the_same():
    tracker = GestureTracker()
    palms = [('Right', synthetic_hand(centre=(0.35, 0.5)), 0.9), ('Right', synthetic_hand(centre=(0.65, 0.5)), 0.9)]
    events, _ = frames(tracker, palms, 0, int(30 * (EXIT_HOLD_SEC + 0.5)))
    assert [e['type'] for e in events].count('exit') == 1


def test_a_single_hand_keeps_its_side_when_the_label_flickers():
    tracker = GestureTracker()
    hand = synthetic_hand(extended=('index',), centre=(0.6, 0.5))
    _, now = frames(tracker, [('Right', hand, 0.9)], 0, 10)
    events, now = frames(tracker, [('Left', hand, 0.6)], now, 3)  # one-off wrong label
    assert [h['side'] for h in tracker.snapshot()] == ['Right']
    assert not [e for e in events if e['type'] == 'pose']


def test_tracker_uses_3d_landmarks_when_given():
    tracker = GestureTracker()
    back_of_open_hand = [('Right', recorded('open_palm'), 0.95, recorded_world('open_palm'))]
    events, _ = frames(tracker, back_of_open_hand, 0, 5)
    assert [e['pose'] for e in events] == ['open_palm']


def test_both_palms_held_exits_once():
    tracker = GestureTracker()
    palms = [('Right', synthetic_hand(centre=(0.65, 0.5)), 0.9), ('Left', synthetic_hand(centre=(0.35, 0.5)), 0.9)]
    events, now = frames(tracker, palms, 0, int(30 * (EXIT_HOLD_SEC - 0.5)))
    assert not [e for e in events if e['type'] == 'exit'], 'not before the hold time'
    events, now = frames(tracker, palms, now, 30)
    assert [e['type'] for e in events].count('exit') == 1


def test_one_palm_does_not_exit_and_idle_timeout_does():
    tracker = GestureTracker(idle_timeout=5)
    one = [('Right', synthetic_hand(), 0.9)]
    events, now = frames(tracker, one, 0, 90)
    assert not [e for e in events if e['type'] in ('exit', 'idle')]
    events, now = frames(tracker, [], now, 30 * 6)
    assert [e['type'] for e in events].count('idle') == 1


def test_lost_hand_ends_its_pose_and_snapshot_has_no_image_data():
    tracker = GestureTracker()
    point = [('Right', synthetic_hand(extended=('index',)), 0.9)]
    _, now = frames(tracker, point, 0, 5)
    snap = tracker.snapshot()
    assert snap[0]['side'] == 'Right' and snap[0]['pose'] == 'point' and len(snap[0]['points']) == 21
    assert set(snap[0]) == {'side', 'pose', 'engaged', 'pinch', 'points'}
    events, _ = frames(tracker, [], now, 15)
    assert {'type': 'pose', 'hand': 'Right', 'pose': 'unknown', 'previous': 'point'} in events
    assert tracker.snapshot() == []


def test_replayed_recording_drives_the_same_events():
    """Recordings (landmarks only, no video) replay through the tracker deterministically."""
    recording = [[('Right', recorded('victory'), 0.95)]] * 6 + [[('Right', recorded('point'), 0.95)]] * 6
    tracker = GestureTracker()
    events = []
    for i, hands in enumerate(recording):
        events += tracker.update(hands, i / 30)
    assert [e['pose'] for e in events if e['type'] == 'pose'] == ['victory', 'point']


# ---- real MediaPipe (skipped where MediaPipe is not installed) --------------

@pytest.mark.parametrize('image,side', [('right_hands.jpg', 'Right'), ('left_hands.jpg', 'Left')])
def test_real_hand_model_reports_the_users_real_hand(image, side):
    """Regression: frames were mirrored before detection, so left and right were swapped."""
    cv2 = pytest.importorskip('cv2')
    pytest.importorskip('mediapipe')
    from pathlib import Path
    from ultron.agents.vision_service import MediaPipeHands
    frame = cv2.imread(str(Path(__file__).parent / 'fixtures' / 'images' / image))
    hands = MediaPipeHands()
    try:
        found = hands.detect(frame, 1.0)
    finally:
        hands.close()
    assert len(found) == 2
    assert {label for label, *_ in found} == {side}
    for _label, landmarks, _score, world in found:
        assert len(landmarks) == 21 and len(world) == 21


# ---- config ----------------------------------------------------------------

def test_shipped_gesture_config_is_valid_and_matches_the_docs_table():
    from ultron.paths import project_root
    cfg = gesture_config.load()
    assert cfg.dominant_hand == 'Right'
    assert cfg.for_gesture('fist_hold').confirm is True, 'locking always asks first'
    doc = (project_root() / 'docs' / 'gestures.md').read_text(encoding='utf-8')
    for m in cfg.mappings:
        assert f'`{m.gesture}`' in doc and m.description in doc, f'{m.gesture} missing from docs/gestures.md'


@pytest.mark.parametrize('broken', [
    {'version': 2, 'mappings': []},
    {'version': 1, 'dominant_hand': 'Middle', 'mappings': []},
    {'version': 1, 'mappings': [{'gesture': 'wink', 'action': 'pointer.move', 'description': 'x'}]},
    {'version': 1, 'mappings': [{'gesture': 'point', 'action': 'format_disk', 'description': 'x'}]},
    {'version': 1, 'mappings': [{'gesture': 'point', 'action': 'pointer.move', 'description': 'a'},
                                {'gesture': 'point', 'action': 'pointer.click', 'description': 'b'}]},
    {'version': 1, 'mappings': [{'gesture': 'point', 'action': 'pointer.move', 'description': ''}]},
])
def test_invalid_gesture_config_is_refused(broken):
    with pytest.raises(ValueError):
        gesture_config.parse(broken)


def test_lock_always_requires_confirmation_even_if_config_says_not():
    cfg = gesture_config.parse({'version': 1, 'mappings': [
        {'gesture': 'fist_hold', 'action': 'system.lock', 'confirm': False, 'description': 'lock'}]})
    assert cfg.mappings[0].confirm is True


# ---- activation ------------------------------------------------------------

@pytest.mark.parametrize('prompt,expected', [
    ('Gesture mode', 'gesture_on'),
    ('Hey Ultron, turn on gesture mode', 'gesture_on'),
    ('Ultron activate gestures please', 'gesture_on'),
    ('Can you start hand tracking?', 'gesture_on'),
    ('Show my hands', 'gesture_on'),
    ('Gesture mode off', 'gesture_off'),
    ('Ultron, stop gestures.', 'gesture_off'),
    ('Exit gesture mode', 'gesture_off'),
    ('Open calculator', None),
    ("Don't turn on gesture mode", None),
    ('What is gesture mode?', None),
    ('Turn on gesture mode and delete my files', None),
])
def test_gesture_voice_commands(prompt, expected):
    assert gesture_command(prompt) == expected


def clap(n=1600, peak=0.8):
    block = [0.003] * n
    for i in range(40):
        block[i] = peak * (1 - i / 40)
    return block


def quiet(n=1600):
    return [0.003] * n


def test_double_clap_triggers_once():
    detector = DoubleClapDetector()
    t = 0.0
    for _ in range(30):
        t += 0.1
        assert not detector.update(quiet(), t)
    assert not detector.update(clap(), t + 0.1)
    assert not detector.update(quiet(), t + 0.2)
    assert detector.update(clap(), t + 0.45)
    assert not detector.update(clap(), t + 0.8), 'refractory period'


def test_single_claps_far_apart_speech_and_muted_sound_do_not_trigger():
    detector = DoubleClapDetector()
    t = 0.0
    for _ in range(30):
        t += 0.1
        detector.update(quiet(), t)
    assert not detector.update(clap(), t + 0.1)
    assert not detector.update(clap(), t + 2.0), 'too far apart'
    rng = random.Random(2)
    speech = [[0.3 * math.sin(i / 7) + rng.uniform(-0.05, 0.05) for i in range(1600)] for _ in range(10)]
    assert not any(detector.update(block, t + 3 + k * 0.1) for k, block in enumerate(speech)), 'speech is not a clap'
    assert not detector.update(clap(), t + 5, muted=True)
    assert not detector.update(clap(), t + 5.3, muted=True), 'claps during ULTRON speech are ignored'


# ---- vision service --------------------------------------------------------

class FakeCamera:
    def __init__(self, width, height):
        self.size = (width, height)
        self.released = False

    def read(self):
        import numpy as np
        return True, np.zeros((self.size[1], self.size[0], 3), dtype=np.uint8)

    def release(self):
        self.released = True


class Recorder:
    def __init__(self):
        self.signals, self.raw = [], []

    def emit(self, kind, payload):
        self.signals.append((kind, payload))

    def emit_raw(self, subject, payload):
        self.raw.append((subject, payload))


def make_service(hands_script, presence=False, camera_fails=False):
    pytest.importorskip('cv2')
    from ultron.agents.vision_service import VisionService
    cameras, spoken = [], []
    script = iter(hands_script)

    def open_camera(width, height):
        if camera_fails:
            raise RuntimeError('Camera 0 could not be opened')
        cameras.append(FakeCamera(width, height))
        return cameras[-1]

    hands = SimpleNamespace(detect=lambda frame, now: next(script, []), close=lambda: None)
    now = [0.0]

    def clock():
        now[0] += 1 / 30
        return now[0]

    service = VisionService(Recorder(), open_camera=open_camera, make_hands=lambda: hands,
                            make_faces=lambda: (lambda frame: []), presence_enabled=presence,
                            clock=clock, speak=spoken.append)
    return service, cameras, spoken


def test_camera_stays_closed_until_gesture_mode_and_is_released_after():
    service, cameras, spoken = make_service([])
    assert asyncio.run(service.step()) is None and cameras == [], 'idle: camera never opened'
    assert service.control('gesture_on', 'ops')['gesture'] is True
    asyncio.run(service.step())
    assert cameras and cameras[0].size == (1280, 720)
    service.control('gesture_off', 'voice')
    asyncio.run(service.step())
    assert cameras[0].released and service.camera is None
    assert spoken == [], 'voice and panel requests answer for themselves'
    subjects = [s for s, _ in service.publisher.raw]
    assert subjects == ['ultron.vision.state', 'ultron.vision.state']


def test_clap_toggles_and_is_spoken_and_unknown_commands_do_nothing():
    service, _, spoken = make_service([])
    assert service.control('gesture_toggle', 'clap')['gesture'] is True
    assert service.control('format_disk', 'evil')['gesture'] is True
    assert service.control('gesture_toggle', 'clap')['gesture'] is False
    assert spoken == ['Gesture mode on. Show me your hands.', 'Gesture mode off.']


def test_both_palms_exit_gesture_mode_and_hands_are_published():
    palms = [('Right', synthetic_hand(centre=(0.65, 0.5)), 0.9), ('Left', synthetic_hand(centre=(0.35, 0.5)), 0.9)]
    service, cameras, spoken = make_service([palms] * 60)
    service.control('gesture_on', 'ops')
    for _ in range(60):
        asyncio.run(service.step())
        if not service.gesture:
            break
    assert service.gesture is False and spoken == ['Gesture mode off.']
    kinds = {kind for kind, _ in service.publisher.signals}
    assert {'hands', 'gesture'} <= kinds
    hands_payload = next(p for k, p in service.publisher.signals if k == 'hands' and p['hands'])
    assert set(hands_payload['hands'][0]) == {'side', 'pose', 'engaged', 'pinch', 'points'}


def test_camera_failure_turns_gesture_mode_back_off_with_a_reason():
    service, _, _ = make_service([], camera_fails=True)
    service.control('gesture_on', 'voice')
    asyncio.run(service.step())
    state = service.state()
    assert state['gesture'] is False and 'could not be opened' in state['error']


def test_presence_mode_uses_low_resolution_and_pauses_for_gestures():
    service, cameras, _ = make_service([], presence=True)
    asyncio.run(service.step())
    assert cameras[-1].size == (320, 240)
    service.control('gesture_on', 'ops')
    asyncio.run(service.step())
    assert cameras[0].released and cameras[-1].size == (1280, 720), 'one camera owner, reopened for hands'


def test_hands_carry_the_camera_aspect_and_resolution_can_be_overridden(monkeypatch):
    """Regression: 640x480 cropped 16:9 webcams, so hands vanished before the edge."""
    pytest.importorskip('numpy')
    from ultron.agents import vision_service
    assert vision_service.gesture_resolution() == (1280, 720)
    monkeypatch.setenv('ULTRON_GESTURE_RESOLUTION', '1920x1080')
    assert vision_service.gesture_resolution() == (1920, 1080)
    monkeypatch.setenv('ULTRON_GESTURE_RESOLUTION', 'huge')
    assert vision_service.gesture_resolution() == (1280, 720)
    monkeypatch.delenv('ULTRON_GESTURE_RESOLUTION')

    recorder = Recorder()
    service = vision_service.VisionService(
        recorder, open_camera=lambda w, h: FakeCamera(w, h),
        make_hands=lambda: SimpleNamespace(detect=lambda frame, now: [], close=lambda: None),
        make_faces=lambda: (lambda frame: []), clock=lambda: 1.0)
    service.control('gesture_on', 'ops')
    asyncio.run(service.step())
    hands = [payload for kind, payload in recorder.signals if kind == 'hands']
    assert hands and abs(hands[-1]['aspect'] - 16 / 9) < 1e-3
