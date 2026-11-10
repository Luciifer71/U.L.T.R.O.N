from ultron.agents.presence_watcher import PresenceTracker, gaze_from_box, largest_face


def test_largest_face_picks_the_closest_and_ignores_junk():
    assert largest_face(None) is None
    assert largest_face([]) is None
    assert largest_face([(0, 0, 0, 10), (10, 10, 30, 30), (5, 5, 60, 50)]) == (5, 5, 60, 50)


def test_gaze_is_mirrored_and_normalised():
    # Face on the left of the camera image = user is on the right of the screen.
    x, y, near = gaze_from_box((0, 0, 32, 24), 320, 240)
    assert x > 0.8 and y > 0.8 and abs(near - 0.1) < 1e-9
    assert gaze_from_box((144, 108, 32, 24), 320, 240)[:2] == (0.0, 0.0)
    x, y, _ = gaze_from_box((288, 216, 32, 24), 320, 240)
    assert x < -0.8 and y < -0.8


def test_presence_needs_two_detections_and_ends_after_absence():
    tracker = PresenceTracker(rate_hz=10, absent_after=1.5, present_after=2)
    face = (144, 108, 32, 24)
    assert tracker.update(face, 320, 240, 0.0) is None          # one frame is not enough
    first = tracker.update(face, 320, 240, 0.1)
    assert first == {'present': True, 'x': 0.0, 'y': 0.0, 'near': 0.1}
    # A brief miss keeps reporting presence (a keep-alive, so the UI does not drop it).
    assert tracker.update(None, 320, 240, 1.0)['present'] is True
    assert tracker.update(None, 320, 240, 1.7) == {'present': False, 'x': 0.0, 'y': 0.0, 'near': 0.1}
    assert tracker.update(None, 320, 240, 2.0) is None            # absence is reported once


def test_positions_are_smoothed_and_throttled():
    tracker = PresenceTracker(rate_hz=5, present_after=1, smoothing=0.5)
    tracker.update((144, 108, 32, 24), 320, 240, 0.0)
    sent = []
    for i in range(1, 11):  # face jumps to the far left of the image for 1 s at 10 fps
        payload = tracker.update((0, 108, 32, 24), 320, 240, i * 0.1)
        if payload:
            sent.append(payload)
    assert 4 <= len(sent) <= 6, 'about 5 updates per second'
    xs = [p['x'] for p in sent]
    assert xs == sorted(xs) and xs[0] < xs[-1] <= 0.9, 'moves gradually toward the face'
