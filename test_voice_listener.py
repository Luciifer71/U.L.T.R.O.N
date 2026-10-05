import asyncio
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from speech_runtime import SpeechConfig


@pytest.fixture
def listener(monkeypatch):
    # PortAudio is intentionally absent on headless test hosts. Fake only the
    # hardware API, then execute the actual listener module and functions.
    sd = SimpleNamespace(InputStream=object, check_input_settings=lambda **kwargs: None,
                         query_devices=lambda **kwargs: {})
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    spec = importlib.util.spec_from_file_location("voice_listener_test", Path(__file__).with_name("voice_listener.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
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
    assert listener.is_valid_command_prompt("open calculator")
    assert not listener.is_valid_command_prompt("um")
