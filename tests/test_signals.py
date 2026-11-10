import asyncio
import json
from types import SimpleNamespace

import pytest

from ultron.control.signals import (
    ModelActivity, SignalPublisher, VoiceLevelMeter, read_vitals, step_signal, vitals_loop,
)


class FakeNats:
    def __init__(self, connected=True, fail=False):
        self.is_connected = connected
        self.fail = fail
        self.sent = []

    async def publish(self, subject, data):
        if self.fail:
            raise ConnectionError('down')
        self.sent.append((subject, json.loads(data)))


class Recorder:
    def __init__(self):
        self.sent = []

    def emit(self, kind, payload):
        self.sent.append((kind, payload))
        return True


def test_publisher_sends_json_on_signal_subject_and_never_raises():
    async def run():
        nc = FakeNats()
        publisher = SignalPublisher(nc)
        assert publisher.emit('vitals', {'cpu': 0.5})
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert nc.sent == [('ultron.signal.vitals', {'cpu': 0.5})]

        broken = SignalPublisher(FakeNats(fail=True))
        assert broken.emit('voice', {'level': 1})
        await asyncio.sleep(0.01)  # failure is swallowed, not raised

        assert not SignalPublisher(FakeNats(connected=False)).emit('voice', {'level': 1})
    asyncio.run(run())


def test_publisher_without_event_loop_is_a_no_op():
    assert SignalPublisher(FakeNats()).emit('voice', {'level': 1}) is False


def test_step_signal_never_carries_the_target():
    payload = step_signal('t1', 2, 3, r'open_resource:C:\Users\private\diary.txt', 'verified')
    assert payload == {'taskId': 't1', 'index': 2, 'total': 3, 'kind': 'open_resource', 'state': 'verified'}
    assert 'diary' not in json.dumps(payload)
    assert step_signal('t', -1, 0, 'x', 'weird')['state'] == 'completed'
    assert step_signal('t', -1, 0, 'x', 'failed') == {'taskId': 't', 'index': 0, 'total': 1, 'kind': 'x', 'state': 'failed'}


def test_voice_level_is_logarithmic_and_clamped():
    assert VoiceLevelMeter.level(0.01, 0.02) == 0.0
    assert VoiceLevelMeter.level(0.04, 0.02) == 0.25
    assert VoiceLevelMeter.level(0.32, 0.02) == 1.0
    assert VoiceLevelMeter.level(10, 0.02) == 1.0
    assert VoiceLevelMeter.level(1, 0) == 0.0


def test_voice_meter_throttles_and_settles_with_a_final_zero():
    now = [0.0]
    meter = VoiceLevelMeter(rate_hz=10, clock=lambda: now[0])
    assert meter.update(0.01, 0.02, speaking=False) is None  # quiet stays quiet
    sent = []
    for _ in range(30):  # 1.5 s of speech in 50 ms steps
        level = meter.update(0.08, 0.02, speaking=True)
        if level is not None:
            sent.append(level)
        now[0] += 0.05
    assert 14 <= len(sent) <= 16 and set(sent) == {0.5}
    assert meter.update(0.08, 0.02, speaking=False) == 0.0
    assert meter.update(0.08, 0.02, speaking=False) is None


def test_read_vitals_normalises_and_survives_missing_psutil():
    fake = SimpleNamespace(cpu_percent=lambda interval=None: 37.5, virtual_memory=lambda: SimpleNamespace(percent=96.7))
    assert read_vitals(fake) == {'cpu': 0.375, 'memory': 0.967}
    broken = SimpleNamespace(cpu_percent=lambda interval=None: 1 / 0)
    assert read_vitals(broken) is None


def test_vitals_loop_publishes_periodically():
    async def run():
        recorder = Recorder()
        task = asyncio.create_task(vitals_loop(recorder, interval=0.01, reader=lambda: {'cpu': 0.1, 'memory': 0.2}))
        # Wait for the condition rather than a fixed time: Windows timers tick
        # about every 15 ms, so a short fixed sleep can see a single publish.
        for _ in range(200):
            if len(recorder.sent) >= 2:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(recorder.sent) >= 2
        assert recorder.sent[0] == ('vitals', {'cpu': 0.1, 'memory': 0.2})
    asyncio.run(run())


def test_model_activity_counts_overlapping_requests():
    now = [10.0]
    recorder = Recorder()
    activity = ModelActivity(recorder, clock=lambda: now[0])
    activity.start()
    activity.start()
    now[0] = 12.5
    activity.end()
    assert recorder.sent == [('model', {'phase': 'start'})]
    activity.end()
    activity.end()  # extra end is ignored
    assert recorder.sent == [('model', {'phase': 'start'}), ('model', {'phase': 'end', 'seconds': 2.5})]
