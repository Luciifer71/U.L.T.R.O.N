"""Launcher regressions without starting services or opening terminals."""
import unittest
import io
import json
import pytest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ultron.cli import start_ultron as launcher
class LauncherTests(unittest.TestCase):
    def test_warmup_uses_selected_trial_profile_without_tools(self):
        opener = MagicMock()
        opener.open.return_value = io.StringIO('{"done": true}')
        settings = {'LLM_THINKING': 'off', 'LLM_CONTEXT': '4096',
                    'LLM_TEMPERATURE': '0', 'LLM_SEED': '42'}
        with patch.dict(launcher.os.environ, settings), patch.object(launcher, 'build_opener', return_value=opener):
            launcher.warm_ollama('http://127.0.0.1:11434', 'qwen3:8b')
        request = opener.open.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload['model'], 'qwen3:8b')
        self.assertIs(payload['think'], False)
        self.assertEqual(payload['options'], {'num_predict': 8, 'temperature': 0,
                                              'num_ctx': 4096, 'seed': 42})
        self.assertNotIn('tools', payload)
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 300)

    def test_default_warmup_does_not_send_thinking_option(self):
        opener = MagicMock()
        opener.open.return_value = io.StringIO('{"done": true}')
        with patch.dict(launcher.os.environ, {}, clear=True), patch.object(launcher, 'build_opener', return_value=opener):
            launcher.warm_ollama('http://127.0.0.1:11434', 'qwen2.5:7b')
        self.assertNotIn('think', json.loads(opener.open.call_args.args[0].data))

    def test_warmup_errors_and_incomplete_responses_fail_readiness(self):
        for data in ('{"done": false}', '{"error": "out of memory"}', 'not json', '[]'):
            with self.subTest(data=data):
                opener = MagicMock()
                opener.open.return_value = io.StringIO(data)
                with patch.object(launcher, 'build_opener', return_value=opener):
                    with self.assertRaisesRegex(launcher.StartupError, 'warmup failed'):
                        launcher.warm_ollama('http://127.0.0.1:11434', 'qwen3:8b')
        with patch.object(launcher, 'build_opener') as build:
            build.return_value.open.side_effect = TimeoutError('timeout')
            with self.assertRaises(launcher.StartupError):
                launcher.warm_ollama('http://127.0.0.1:11434', 'qwen3:8b')

    def test_existing_nats_is_reused(self):
        with patch.object(launcher, 'nats_ready', return_value=True), patch.object(launcher, 'find_executable') as find:
            launcher.ensure_nats('nats://127.0.0.1:4222')
            find.assert_not_called()

    def test_remote_nats_failure_does_not_start_docker(self):
        with patch.object(launcher, 'nats_ready', return_value=False), patch.object(launcher, 'find_executable') as find:
            with self.assertRaises(launcher.StartupError):
                launcher.ensure_nats('nats://example.invalid:4222')
            find.assert_not_called()

    def test_docker_failure_stops_before_components(self):
        with patch.object(launcher, 'nats_ready', return_value=False), patch.object(launcher, 'find_executable', return_value='docker.exe'), patch.object(launcher.subprocess, 'run', side_effect=[SimpleNamespace(returncode=0), SimpleNamespace(returncode=1)]):
            with self.assertRaises(launcher.StartupError):
                launcher.ensure_nats('nats://127.0.0.1:4222')

    def test_stopped_nats_allows_compose_to_reconcile_moved_config(self):
        calls = []
        def run(command, **kwargs):
            calls.append((command, kwargs))
            return SimpleNamespace(returncode=0)
        with patch.object(launcher, 'nats_ready', side_effect=[False, True]), patch.object(launcher, 'find_executable', return_value='docker.exe'), patch.object(launcher.subprocess, 'run', side_effect=run):
            launcher.ensure_nats('nats://127.0.0.1:4222')
        command, options = calls[1]
        self.assertEqual(command, ['docker.exe', 'compose', 'up', '-d', '--no-deps', '--pull', 'never', 'nats'])
        self.assertEqual(options['cwd'], launcher.ROOT)
        self.assertEqual(options['timeout'], 90)

    def test_running_ollama_is_reused(self):
        with patch.object(launcher, 'ollama_models', return_value={'models': [{'name': 'qwen2.5:7b'}]}), patch.object(launcher, 'start_console') as start:
            launcher.ensure_ollama('http://127.0.0.1:11434', 'qwen2.5:7b')
            start.assert_not_called()

    def test_missing_model_does_not_pull_automatically(self):
        with patch.object(launcher, 'ollama_models', return_value={'models': []}), patch.object(launcher, 'start_console') as start:
            with self.assertRaisesRegex(launcher.StartupError, 'ollama pull'):
                launcher.ensure_ollama('http://127.0.0.1:11434', 'qwen2.5:7b')
            start.assert_not_called()

    def test_unavailable_remote_ollama_does_not_start_local_server(self):
        with patch.object(launcher, 'ollama_models', return_value=None), patch.object(launcher, 'start_console') as start:
            with self.assertRaises(launcher.StartupError):
                launcher.ensure_ollama('http://example.invalid:11434', 'qwen2.5:7b')
            start.assert_not_called()

    def test_missing_local_ollama_starts_server_and_waits(self):
        with patch.object(launcher, 'ollama_models', return_value=None), patch.object(launcher, 'find_executable', return_value='ollama.exe'), patch.object(launcher, 'start_console') as start, patch.object(launcher, 'wait_for', return_value={'models': [{'name': 'qwen2.5:7b'}]}):
            launcher.ensure_ollama('http://127.0.0.1:11434', 'qwen2.5:7b')
            start.assert_called_once_with(['ollama.exe', 'serve'])

    def test_duplicate_detection_is_scoped_to_checkout(self):
        fake = SimpleNamespace(NoSuchProcess=ProcessLookupError, AccessDenied=PermissionError)
        processes = [
            SimpleNamespace(info={'cwd': str(launcher.ROOT), 'cmdline': ['python', 'brain_agent.py']}),
            SimpleNamespace(info={'cwd': str(launcher.ROOT), 'cmdline': ['python', 'start_ultron.py', '--component', 'voice_listener']}),
            SimpleNamespace(info={'cwd': str(launcher.ROOT.parent), 'cmdline': ['python', 'action_daemon.py']}),
        ]
        with patch.dict('sys.modules', {'psutil': fake}):
            self.assertEqual(launcher.running_components(launcher.ROOT, processes), {'brain_agent', 'voice_listener'})

    def test_wait_has_bounded_timeout(self):
        with patch.object(launcher.time, 'monotonic', side_effect=[0, 2]), patch.object(launcher.time, 'sleep') as sleep:
            with self.assertRaises(launcher.StartupError):
                launcher.wait_for(lambda: False, 'test service', timeout=1)
            sleep.assert_not_called()

    def test_nats_probe_checks_greeting_not_just_port(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.recv.return_value = b'HTTP '
        with patch.object(launcher.socket, 'create_connection', return_value=connection):
            self.assertFalse(launcher.nats_ready('nats://127.0.0.1:4222'))


@pytest.mark.parametrize('warmup_fails', [False, True])
def test_main_opens_components_early_and_the_listener_after_warmup(monkeypatch, tmp_path, warmup_fails):
    from contextlib import nullcontext
    import sys
    import dotenv
    import psutil
    executable = tmp_path / '.venv' / 'Scripts' / 'python.exe'
    executable.parent.mkdir(parents=True)
    executable.touch()
    for component in launcher.COMPONENTS:
        location = tmp_path / 'src' / 'ultron' / 'agents' / (component + '.py')
        location.parent.mkdir(parents=True, exist_ok=True)
        location.touch()
    events = []
    monkeypatch.setattr(sys, 'argv', ['start_ultron.py'])
    monkeypatch.setattr(launcher, 'ROOT', tmp_path)
    monkeypatch.setattr(launcher, 'os', SimpleNamespace(name='nt', getenv=lambda key, default: default))
    monkeypatch.setattr(launcher, 'sys', SimpleNamespace(executable=str(executable), argv=['start_ultron.py']))
    monkeypatch.setattr(launcher.importlib.util, 'find_spec', lambda name: object())
    monkeypatch.setattr(dotenv, 'load_dotenv', lambda *args, **kwargs: None)
    monkeypatch.setattr(psutil, 'process_iter', lambda attrs: [])
    monkeypatch.setattr(launcher, 'startup_lock', nullcontext)
    monkeypatch.setattr(launcher, 'ensure_nats', lambda url: None)
    monkeypatch.setattr(launcher, 'ensure_ollama', lambda *args: None)
    def warm(*args):
        events.append('warm')
        if warmup_fails:
            raise launcher.StartupError('test warmup failed')
    monkeypatch.setattr(launcher, 'warm_ollama', warm)
    monkeypatch.setattr(launcher, 'start_console', lambda command: events.append(command[-1]))
    assert launcher.main() == (1 if warmup_fails else 0)
    early = [c for c in launcher.COMPONENTS if c not in launcher.AFTER_WARMUP]
    # Daemon, brain and vision open while the model warms; the microphone only
    # after a successful warmup (so the model gets GPU memory first).
    assert events == early + ['warm'] + ([] if warmup_fails else list(launcher.AFTER_WARMUP))
    assert 'voice_listener' in launcher.AFTER_WARMUP


def test_nats_and_ollama_start_together_and_timing_is_reported(monkeypatch, capsys):
    import threading
    nats_started, ollama_started = threading.Event(), threading.Event()
    def nats(url):
        nats_started.set()
        assert ollama_started.wait(2), 'Ollama must not wait for NATS'
    def ollama(host, model):
        ollama_started.set()
        assert nats_started.wait(2), 'NATS must not wait for Ollama'
    monkeypatch.setattr(launcher, 'ensure_nats', nats)
    monkeypatch.setattr(launcher, 'ensure_ollama', ollama)
    monkeypatch.setattr(launcher, 'warm_ollama', lambda *a: None)
    monkeypatch.setattr(launcher, 'model_placement', lambda *a: None)
    monkeypatch.setattr(launcher, 'running_components', lambda *a: set())
    launched = []
    launcher.launch_all(launcher.COMPONENTS, 'python', SimpleNamespace(process_iter=lambda attrs: []),
                        launch=launched.append)
    assert sorted(launched) == sorted(launcher.COMPONENTS)
    report = capsys.readouterr().out
    assert '[STARTUP TIMING]' in report
    for step in ('NATS ready', 'Ollama ready', 'Model warmup', 'total'):
        assert step in report


def test_native_nats_is_preferred_over_docker(monkeypatch, tmp_path):
    exe = tmp_path / 'tools' / 'nats' / 'nats-server.exe'
    exe.parent.mkdir(parents=True)
    exe.touch()
    ready = iter([False, True])
    started = []
    monkeypatch.setattr(launcher, 'ROOT', tmp_path)
    monkeypatch.setattr(launcher, 'nats_ready', lambda url: next(ready))
    monkeypatch.setattr(launcher.native_nats, 'start', lambda root, path: started.append(path))
    monkeypatch.setattr(launcher, 'start_docker_nats', lambda: pytest.fail('Docker must not be used'))
    monkeypatch.setattr(launcher.time, 'sleep', lambda s: None)
    assert launcher.ensure_nats('nats://127.0.0.1:4222') == 'native'
    assert started == [exe]


def test_docker_is_the_fallback_without_native_nats(monkeypatch, tmp_path, capsys):
    ready = iter([False, True])
    docker = []
    monkeypatch.setattr(launcher, 'ROOT', tmp_path)
    monkeypatch.setattr(launcher, 'nats_ready', lambda url: next(ready))
    monkeypatch.setattr(launcher, 'start_docker_nats', lambda: docker.append(True))
    monkeypatch.setattr(launcher.time, 'sleep', lambda s: None)
    assert launcher.ensure_nats('nats://127.0.0.1:4222') == 'docker'
    assert docker == [True]
    assert 'setup-nats' in capsys.readouterr().out


if __name__ == '__main__':
    unittest.main()


def test_warmup_reports_separate_loading_and_generation(capsys):
    opener = MagicMock()
    opener.open.return_value = io.StringIO(json.dumps({'done':True, 'load_duration':190000000000,
        'prompt_eval_duration':1000000000, 'eval_duration':2000000000, 'eval_count':8}))
    with patch.object(launcher, 'build_opener', return_value=opener):
        launcher.warm_ollama('http://127.0.0.1:11434', 'qwen3:8b')
    output = capsys.readouterr().out
    assert '"load_seconds": 190.0' in output and '"eval_seconds": 2.0' in output
    assert '"eval_count": 8' in output


@pytest.mark.parametrize('vram,expected', [(5_000_000_000, '100% on the GPU'), (2_000_000_000, 'only 40%')])
def test_model_placement_reports_cpu_offload(vram, expected):
    opener = MagicMock()
    opener.open.return_value = io.StringIO(json.dumps({'models': [
        {'name': 'qwen3:8b', 'size': 5_000_000_000, 'size_vram': vram}]}))
    share, message = launcher.model_placement('http://127.0.0.1:11434', 'qwen3:8b', opener)
    assert expected in message
    assert share == vram / 5_000_000_000


def test_model_placement_is_silent_when_ollama_does_not_say():
    opener = MagicMock()
    opener.open.side_effect = OSError('down')
    assert launcher.model_placement('http://127.0.0.1:11434', 'qwen3:8b', opener) is None
