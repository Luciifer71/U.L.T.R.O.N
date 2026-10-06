"""Launcher regressions without starting services or opening terminals."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import start_ultron as launcher


class LauncherTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
