import asyncio
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from speech_runtime import SpeechConfig


def test_saved_settings_loaded_before_listener_configuration(monkeypatch, tmp_path):
    import dotenv
    settings = tmp_path / ".env"
    settings.write_text("NATS_URL=nats://127.0.0.1:4222\nAUDIO_INPUT_DEVICE=1\nWHISPER_DEVICE=cuda\nWHISPER_MODEL_SIZE=small.en\n")
    original_loader = dotenv.load_dotenv
    def load_settings(path, override):
        assert path == (Path(__file__).resolve().parents[1] / '.env')
        assert override is False
        return original_loader(settings, override=override)
    monkeypatch.setattr(dotenv, "load_dotenv", load_settings)
    for name in ("NATS_URL", "AUDIO_INPUT_DEVICE", "WHISPER_DEVICE"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    monkeypatch.setenv("WHISPER_MODEL_SIZE", "medium.en")
    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace())
    spec = importlib.util.spec_from_file_location("listener_saved_settings", (Path(__file__).resolve().parents[1] / 'voice_listener.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.MIC_DEVICE is None
    assert module.CONFIGURED_MIC_DEVICE == "1"
    assert module.NATS_URL == "nats://127.0.0.1:4222"
    assert module.SpeechConfig.from_env().device == "cuda"
    assert module.SpeechConfig.from_env().model == "medium.en"


@pytest.fixture
def listener(monkeypatch):
    # PortAudio is intentionally absent on headless test hosts. Fake only the
    # hardware API, then execute the actual listener module and functions.
    sd = SimpleNamespace(InputStream=object, check_input_settings=lambda **kwargs: None,
                         query_devices=lambda **kwargs: {})
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    spec = importlib.util.spec_from_file_location("voice_listener_test", (Path(__file__).resolve().parents[1] / 'voice_listener.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "create_speech_activity", lambda: None)
    return module


def test_engine_uses_configured_language_and_retains_filter(monkeypatch, listener):
    calls = []
    def transcribe(audio, **kwargs):
        calls.append(kwargs)
        return iter([SimpleNamespace(text="Hey Ultron, open calculator.")]), None
    model = SimpleNamespace(transcribe=transcribe)
    monkeypatch.setattr(listener, "load_whisper_model", lambda config: (model, "cuda", {"device": "cuda"}))
    engine = listener.WhisperEngine(SpeechConfig(language="hi"))
    assert engine.transcribe(np.ones(16000, dtype=np.float32)) == "Hey Ultron, open calculator."
    assert calls[0]["language"] == "hi"
    assert calls[0]["beam_size"] == 5
    model.transcribe = lambda *args, **kwargs: (iter([SimpleNamespace(text="Thank you for watching.")]), None)
    assert engine.transcribe(np.ones(16000, dtype=np.float32)) is None


def test_microphone_failure_closes_partial_stream_and_raises(monkeypatch, listener):
    closed = []
    class Stream:
        def start(self):
            raise RuntimeError("microphone permission denied")
        def close(self):
            closed.append(True)
    monkeypatch.setattr(listener.sd, "check_input_settings", lambda **kwargs: None)
    monkeypatch.setattr(listener.sd, "query_devices", lambda **kwargs: {"name": "test"})
    monkeypatch.setattr(listener.sd, "InputStream", lambda **kwargs: Stream())
    stream = listener.ResilientAudioStream(None, None)
    with pytest.raises(RuntimeError, match="Microphone startup failed"):
        stream.start()
    assert closed == [True]
    assert stream.stream is None


def test_invalid_input_settings_do_not_open_stream(monkeypatch, listener):
    def invalid(**kwargs):
        raise RuntimeError("unsupported sample rate")
    monkeypatch.setattr(listener.sd, "check_input_settings", invalid)
    monkeypatch.setattr(listener.sd, "InputStream", lambda **kwargs: pytest.fail("must not open invalid stream"))
    with pytest.raises(RuntimeError, match="Microphone startup failed"):
        listener.ResilientAudioStream(None, None).start()


def test_calibration_does_not_wait_forever_for_dead_microphone(monkeypatch, listener):
    original_wait_for = asyncio.wait_for
    async def short_wait(awaitable, timeout):
        assert timeout == 5.0
        return await original_wait_for(awaitable, timeout=0.001)
    monkeypatch.setattr(listener.asyncio, "wait_for", short_wait)
    async def run():
        with pytest.raises(asyncio.TimeoutError):
            await listener.calibrate_ambient_noise(asyncio.Queue(), samples=1)
    asyncio.run(run())


def test_existing_wake_word_and_command_route_is_preserved(listener):
    assert listener.extract_wake_word_command("Hey Ultron, open calculator.") == (True, "open calculator.")
    assert listener.extract_wake_word_command("ambient speech") == (False, "")


@pytest.mark.parametrize('text', ['Open Ultron smoke note and not pad.', 'run Ultron smoke script.'])
def test_resource_name_inside_command_is_not_a_wake_prefix(listener, text):
    assert listener.extract_wake_word_command(text) == (False, '')


def test_wake_prefix_preserves_later_ultron_filename(listener):
    assert listener.extract_wake_word_command('Hey Ultron, run Ultron smoke script.') == (True, 'run Ultron smoke script.')
    assert listener.extract_wake_word_command('Okay, so, hey Ultron, open calculator.') == (True, 'open calculator.')
    assert listener.is_valid_command_prompt("open calculator")
    assert not listener.is_valid_command_prompt("um")


def test_callback_copies_capture_audio_and_remembers_tts_gate(listener):
    frames = []
    gate = SimpleNamespace(is_speaking=True)
    stream = listener.ResilientAudioStream(SimpleNamespace(push=frames.append), None, gate)
    data = np.ones((1024, 1), dtype=np.float32)
    stream._audio_callback(data, 1024, None, False)
    data[:] = 0
    gate.is_speaking = False
    assert frames[0].muted is True
    assert np.all(frames[0].samples == 1)
    stream._audio_callback(data, 1024, None, True)
    assert frames[1].sequence == frames[0].sequence + 1
    assert frames[1].discontinuity is True


def test_calibration_consumes_captured_frames(listener):
    async def run():
        queue = asyncio.Queue()
        await queue.put(listener.AudioFrame(np.zeros(1024), listener.time.monotonic(), 1))
        assert await listener.calibrate_ambient_noise(queue, samples=1) == 0.008
    asyncio.run(run())


def test_calibration_ignores_tts_and_damaged_audio(listener):
    async def run():
        queue = asyncio.Queue()
        await queue.put(listener.AudioFrame(np.ones(1024), listener.time.monotonic(), 1, muted=True))
        await queue.put(listener.AudioFrame(np.ones(1024), listener.time.monotonic(), 2, discontinuity=True))
        await queue.put(listener.AudioFrame(np.zeros(1024), listener.time.monotonic(), 3))
        assert await listener.calibrate_ambient_noise(queue, samples=1) == 0.008
    asyncio.run(run())


def test_calibration_is_bounded_even_if_tts_never_releases_gate(listener, monkeypatch):
    clock = iter([0, 0, 11])
    monkeypatch.setattr(listener, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    async def run():
        queue = asyncio.Queue()
        await queue.put(listener.AudioFrame(np.ones(1024), 0, 1, muted=True))
        with pytest.raises(RuntimeError, match="No clean"):
            await listener.calibrate_ambient_noise(queue, samples=1)
    asyncio.run(run())


@pytest.mark.parametrize('slow_inference,recover_stream', [(False, False), (True, False), (False, 'dead'), (False, 'device')])
def test_main_routes_complete_utterance_and_cleans_up_on_cancel(listener, monkeypatch, slow_inference, recover_stream):
    import json
    from threading import Event
    calls = []
    streams = []
    mailboxes = []
    captured_while_transcribing = Event()
    mailbox_type = listener.AudioMailbox
    class ObservedMailbox(mailbox_type):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.consumed = asyncio.Queue()
        async def get(self):
            frame = await super().get()
            self.consumed.put_nowait(frame.sequence)
            return frame
    def mailbox(*args, **kwargs):
        result = ObservedMailbox(*args, **kwargs)
        mailboxes.append(result)
        return result
    monkeypatch.setattr(listener, 'AudioMailbox', mailbox)
    async def run():
        intent_received = asyncio.Event()
        inference_started = asyncio.Event()
        loop = asyncio.get_running_loop()
        class Nats:
            is_connected = True
            async def connect(self, *args, **kwargs):
                pass
            async def subscribe(self, *args, **kwargs):
                pass
            async def request(self, *args, **kwargs):
                from types import SimpleNamespace
                return SimpleNamespace(data=b'{"speaking": false, "version": 0}')
            async def publish(self, subject, payload):
                if subject == "ultron.intent":
                    calls.append(json.loads(payload))
                    intent_received.set()
            async def flush(self):
                pass
            async def drain(self):
                pass
            async def close(self):
                self.is_connected = False
        class Whisper:
            def transcribe(self, samples):
                assert len(samples) == 38 * 1024
                if slow_inference:
                    loop.call_soon_threadsafe(inference_started.set)
                    assert captured_while_transcribing.wait(15)
                return "Hey Ultron, open calculator."
        class Stream:
            def __init__(self, **kwargs):
                self.callback = kwargs["callback"]
                self.closed = False
                streams.append(self)
            def start(self):
                async def produce():
                    if recover_stream and len(streams) == 1:
                        return  # Simulate a driver that stopped delivering frames.
                    if recover_stream:
                        for _ in range(30):
                            self.callback(np.zeros((1024, 1), dtype=np.float32), 1024, None, False)
                            await mailboxes[0].consumed.get()
                    for index in range(38):
                        data = np.full((1024, 1), 0.1 if 8 <= index < 16 else 0.0, dtype=np.float32)
                        self.callback(data, 1024, None, False)
                        await mailboxes[0].consumed.get()
                    if slow_inference:
                        await inference_started.wait()
                        for _ in range(100):
                            self.callback(np.zeros((1024, 1), dtype=np.float32), 1024, None, False)
                            # Inference remains blocked until the consumer has
                            # drained more than a mailbox capacity of frames.
                            await mailboxes[0].consumed.get()
                        captured_while_transcribing.set()
                self.producer = asyncio.create_task(produce())
            def stop(self):
                self.producer.cancel()
            def close(self):
                self.closed = True
        async def calibrate(*args, **kwargs):
            return 0.008
        async def visual(*args, **kwargs):
            pass
        monkeypatch.setattr(listener, "NATS", Nats)
        monkeypatch.setattr(listener, "WhisperEngine", Whisper)
        monkeypatch.setattr(listener, "calibrate_ambient_noise", calibrate)
        monkeypatch.setattr(listener, "publish_visual_event", visual)
        monkeypatch.setattr(listener.sd, "InputStream", Stream)
        monkeypatch.setattr(listener.sd, '_terminate', lambda: None, raising=False)
        monkeypatch.setattr(listener.sd, '_initialize', lambda: None, raising=False)
        if recover_stream == 'device':
            old = [{'index': 0, 'name': 'Microphone Array', 'api': 'MME'}]
            new = old + [{'index': 1, 'name': 'Headset Microphone', 'api': 'MME'}]
            monkeypatch.setattr(listener, 'inventory', lambda sd: new if streams else old)
            async def probe(): return new
            monkeypatch.setattr(listener, 'probe_inventory', probe)
            original_sleep = asyncio.sleep
            async def quick_device_check(delay):
                await original_sleep(0.01 if delay == 10 else delay)
            monkeypatch.setattr(listener.asyncio, 'sleep', quick_device_check)
        if recover_stream == 'dead':
            original_wait = asyncio.wait_for
            async def quick_dead_capture(awaitable, timeout):
                return await original_wait(awaitable, 0.01 if timeout == 5.0 and len(streams) == 1 else timeout)
            monkeypatch.setattr(listener.asyncio, 'wait_for', quick_dead_capture)
        task = asyncio.create_task(listener.main())
        try:
            await asyncio.wait_for(intent_received.wait(), 10)
        finally:
            captured_while_transcribing.set()
            task.cancel()
            await task
        assert all(stream.closed for stream in streams)
        assert len(streams) == (2 if recover_stream else 1)
        assert mailboxes[0].dropped_frames == 0
    asyncio.run(run())
    assert calls == [{"prompt": "open calculator."}]


@pytest.mark.parametrize('metrics', [{'avg_logprob': -1.1}, {'compression_ratio': 2.5}])
def test_uncertain_segment_rejects_whole_command(listener, monkeypatch, metrics):
    model = SimpleNamespace(transcribe=lambda *a, **k: (iter([
        SimpleNamespace(text='Open calculator and'),
        SimpleNamespace(text='notion', **metrics),
    ]), None))
    monkeypatch.setattr(listener, 'load_whisper_model', lambda config: (model, 'cpu', {}))
    engine = listener.WhisperEngine()
    assert engine.transcribe(np.ones(16000)) is None
    assert 'uncertain speech' in engine.last_rejection
    model.transcribe = lambda *a, **k: (iter([SimpleNamespace(text='Open calculator.', avg_logprob=-0.2, compression_ratio=1.2)]), None)
    assert engine.transcribe(np.ones(16000)) == 'Open calculator.'
    assert engine.last_rejection is None


def test_gate_starts_muted_and_rejects_stale_idle_snapshot(listener):
    async def run():
        gate = listener.AcousticGate()
        assert gate.is_speaking
        await gate.set_speaking(False, 10)
        assert not gate.is_speaking
        await gate.set_speaking(True, 12)
        await gate.set_speaking(False, 11)
        assert gate.is_speaking
        await gate.set_speaking(False, 13)
        assert not gate.is_speaking
    asyncio.run(run())


@pytest.mark.parametrize('text, expected', [
    ('Hey Ultron, Hey Ultron,', ''),
    ('Ultron! Hey Ultron. Hello Ultron?', ''),
    ('Hey Ultron, hey Ultron, open calculator.', 'open calculator.'),
    ('Hey Ultron, run Ultron smoke script.', 'run Ultron smoke script.'),
])
def test_repeated_wake_prefixes_do_not_become_model_commands(listener, text, expected):
    assert listener.extract_wake_word_command(text) == (True, expected)


def test_auto_selection_falls_back_when_headset_cannot_open(listener, monkeypatch):
    attempted = []
    monkeypatch.setattr(listener, 'MIC_DEVICE', None)
    monkeypatch.setattr(listener, 'inventory', lambda sd: [
        {'index': 1, 'name': 'Microphone Array', 'api': 'MME'},
        {'index': 2, 'name': 'Headset Microphone', 'api': 'MME'}])
    def check(**kwargs):
        attempted.append(kwargs['device'])
        if kwargs['device'] == 2:
            raise RuntimeError('headset unavailable')
    monkeypatch.setattr(listener.sd, 'check_input_settings', check)
    class Stream:
        def __init__(self, **kwargs): self.device = kwargs['device']
        def start(self): pass
    monkeypatch.setattr(listener.sd, 'InputStream', Stream)
    manager = listener.ResilientAudioStream(None, None)
    manager.start()
    assert attempted == [2, 1] and manager.stream.device == 1


def test_explicit_microphone_override_is_preserved(listener, monkeypatch):
    monkeypatch.setattr(listener, 'MIC_DEVICE', 7)
    monkeypatch.setattr(listener, 'inventory', lambda sd: [
        {'index': 2, 'name': 'Headset Microphone', 'api': 'MME'}])
    class Stream:
        def __init__(self, **kwargs): self.device = kwargs['device']
        def start(self): pass
    monkeypatch.setattr(listener.sd, 'InputStream', Stream)
    manager = listener.ResilientAudioStream(None, None)
    manager.start()
    assert manager.stream.device == 7


def test_refresh_closes_stream_before_reinitializing_portaudio(listener, monkeypatch):
    calls = []
    monkeypatch.setattr(listener.sd, '_terminate', lambda: calls.append('terminate'), raising=False)
    monkeypatch.setattr(listener.sd, '_initialize', lambda: calls.append('initialize'), raising=False)
    class Stream:
        def __init__(self, **kwargs): pass
        def start(self): calls.append('start')
        def stop(self): calls.append('stop')
        def close(self): calls.append('close')
    monkeypatch.setattr(listener.sd, 'InputStream', Stream)
    manager = listener.ResilientAudioStream(None, None)
    manager.start()
    manager.start(refresh=True)
    assert calls == ['start', 'stop', 'close', 'terminate', 'initialize', 'start']
    assert manager.generation == 2 and manager._first_frame


@pytest.mark.parametrize('text, expected', [
    ('Very good. Hey Ultron, Hey Ultron.', (True, '')),
    ('Thank you! Hey Ultron, open calculator.', (True, 'open calculator.')),
    ('He said hey Ultron open calculator.', (False, '')),
    ('If I say hey Ultron open calculator.', (False, '')),
    ('Do not say hey Ultron.', (False, '')),
    ('"Very good. Hey Ultron, open calculator."', (False, '')),
    ('Very good. Open Ultron notes.', (False, '')),
])
def test_only_short_acknowledgements_before_direct_wake_are_accepted(listener, text, expected):
    assert listener.extract_wake_word_command(text) == expected


def test_pinned_input_mode_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv('AUDIO_INPUT_MODE', 'pinned')
    monkeypatch.setenv('AUDIO_INPUT_DEVICE', '3')
    monkeypatch.setitem(sys.modules, 'sounddevice', SimpleNamespace())
    spec = importlib.util.spec_from_file_location('pinned_listener', (Path(__file__).resolve().parents[1] / 'voice_listener.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.MIC_DEVICE == 3
