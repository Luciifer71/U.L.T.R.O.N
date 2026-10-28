"""Exercise actual daemon cancellation without a speaker or external TTS."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest


@pytest.fixture
def daemon_module(monkeypatch):
    music = SimpleNamespace(load=lambda _: None, play=lambda: None,
                            get_busy=lambda: True, stop=lambda: None)
    monkeypatch.setitem(sys.modules, 'pygame', SimpleNamespace(mixer=SimpleNamespace(init=lambda **kw: None, music=music)))
    monkeypatch.setitem(sys.modules, 'edge_tts', SimpleNamespace())
    spec = importlib.util.spec_from_file_location('testable_action_daemon', Path(__file__).with_name('action_daemon.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_cancel_stops_playback_and_releases_speaking_state(daemon_module):
    module = daemon_module
    async def run():
        states, stopped = [], []
        started = asyncio.Event()
        async def publish(subject, payload): states.append(json.loads(payload)['speaking'])
        async def flush(): pass
        class Communicate:
            def __init__(self, *args, **kwargs): pass
            async def stream(self): yield {'type':'audio','data':b'audio'}
        module.edge_tts.Communicate = Communicate
        module.pygame.mixer.music.play = started.set
        module.pygame.mixer.music.stop = lambda: stopped.append(True)
        voice = module.UltronVoiceEngine(SimpleNamespace(is_connected=True, publish=publish, flush=flush), asyncio.get_running_loop())
        task = asyncio.create_task(voice.speak_and_wait('test'))
        await asyncio.wait_for(started.wait(), 1)
        assert voice.speaking and states == [True]
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert stopped and states == [True, False] and not voice.speaking
    asyncio.run(run())


def test_daemon_registers_snapshot_before_startup_speech(daemon_module):
    module = daemon_module
    async def run():
        handlers, replies = {}, []
        class Nats:
            is_connected = True
            async def connect(self, *a): pass
            async def subscribe(self, subject, cb): handlers[subject] = cb
            async def flush(self): pass
            async def close(self): pass
            async def publish(self, subject, payload): replies.append((subject,json.loads(payload)))
        daemon = module.ActionDaemon(); daemon.nc = Nats()
        class Voice:
            speaking = True
            state_version = 123
            def __init__(self, *a, **kw): pass
            async def speak_and_wait(self, text):
                assert 'ultron.voice.state' in handlers
                await asyncio.Event().wait()
        module.UltronVoiceEngine = Voice
        task = asyncio.create_task(daemon.start())
        for _ in range(10): await asyncio.sleep(0)
        await handlers['ultron.voice.state'](SimpleNamespace(reply='reply'))
        assert replies[-1] == ('reply', {'speaking': True, 'version':123})
        await handlers['ultron.voice.cancel'](SimpleNamespace())
        daemon._shutdown_event.set()
        await asyncio.wait_for(task, 1)
    asyncio.run(run())


@pytest.mark.parametrize('stalled_phase', ['synthesis', 'playback'])
def test_speech_timeout_releases_microphone_gate(daemon_module, monkeypatch, stalled_phase):
    module = daemon_module
    async def run():
        states, stopped = [], []
        async def publish(subject, payload): states.append(json.loads(payload)['speaking'])
        async def flush(): pass
        class Communicate:
            def __init__(self, *args, **kwargs): pass
            async def stream(self):
                if stalled_phase == 'synthesis': await asyncio.Event().wait()
                yield {'type': 'audio', 'data': b'audio'}
        module.edge_tts.Communicate = Communicate
        module.pygame.mixer.music.stop = lambda: stopped.append(True)
        original_timeout = asyncio.timeout
        monkeypatch.setattr(module.asyncio, 'timeout', lambda delay: original_timeout(0.01))
        voice = module.UltronVoiceEngine(SimpleNamespace(is_connected=True, publish=publish, flush=flush), asyncio.get_running_loop())
        await voice.speak_and_wait('test')
        assert stopped and states == [True, False] and not voice.speaking
    asyncio.run(run())


def test_cancel_during_speaking_notification_still_releases_gate(daemon_module):
    module = daemon_module
    async def run():
        entered = asyncio.Event()
        states = []
        async def publish(subject, payload):
            state = json.loads(payload)['speaking']
            states.append(state)
            if state:
                entered.set()
                await asyncio.Event().wait()
        async def flush(): pass
        voice = module.UltronVoiceEngine(SimpleNamespace(is_connected=True, publish=publish, flush=flush), asyncio.get_running_loop())
        task = asyncio.create_task(voice.speak_and_wait('test'))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert states == [True, False] and not voice.speaking
    asyncio.run(run())


@pytest.mark.parametrize('payload, expected', [
    ({'text': 'full detailed response', 'speech': 'short response'}, 'short response'),
    ({'text': 'text-only response'}, 'text-only response'),
    ({'text': 'do not speak', 'speech': ''}, None),
])
def test_daemon_uses_explicit_speech_instead_of_full_text(daemon_module, payload, expected):
    module = daemon_module
    async def run():
        spoken = []
        daemon = module.ActionDaemon()
        daemon.speech_queue = SimpleNamespace(submit=lambda text, **kw: spoken.append(text))
        await daemon.message_handler(SimpleNamespace(subject='ultron.voice', data=json.dumps(payload).encode()))
        assert spoken == ([] if expected is None else [expected])
    asyncio.run(run())


@pytest.mark.parametrize('audio,busy,expected', [
    (b'', [], 'returned no audio'),
    (b'audio', [False], 'did not start playback'),
    (b'audio', [True, False], 'TTS PLAYBACK FINISHED'),
])
def test_playback_evidence_and_no_automatic_replay(daemon_module, caplog, audio, busy, expected):
    module = daemon_module
    async def run():
        plays = []
        class Communicate:
            def __init__(self, *args, **kwargs): pass
            async def stream(self):
                yield {'type': 'audio', 'data': audio}
        module.edge_tts.Communicate = Communicate
        states = iter(busy)
        module.pygame.mixer.music.get_busy = lambda: next(states)
        module.pygame.mixer.music.play = lambda: plays.append(True)
        voice = module.UltronVoiceEngine(None, asyncio.get_running_loop())
        with caplog.at_level('INFO'):
            await voice.speak_and_wait('startup')
        assert expected in caplog.text
        assert len(plays) == bool(audio)
        assert not voice.speaking
    asyncio.run(run())
