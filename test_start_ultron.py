"""Launcher regressions without starting services or opening terminals."""
import unittest
import io
import json
import pytest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import start_ultron as launcher


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
        self.assertEqual(payload['options'], {'num_predict': 1, 'temperature': 0,
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
def test_main_warms_before_any_component_and_stops_on_failure(monkeypatch, tmp_path, warmup_fails):
    from contextlib import nullcontext
    import sys
    import dotenv
    import psutil
    executable = tmp_path / '.venv' / 'Scripts' / 'python.exe'
    executable.parent.mkdir(parents=True)
    executable.touch()
    for component in launcher.COMPONENTS:
        (tmp_path / (component + '.py')).touch()
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
    assert events == (['warm'] if warmup_fails else ['warm', *launcher.COMPONENTS])


if __name__ == '__main__':
    unittest.main()
