"""Check real entry points and paths without models, services or devices."""
import os
from pathlib import Path
import subprocess
import sys

from ultron.paths import project_root
from ultron.cli import start_ultron
from ultron.core import memory_db

ROOT = Path(__file__).resolve().parents[1]


def clean_env():
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    env.pop('ULTRON_PROJECT_ROOT', None)
    return env


def test_source_dispatch_from_unrelated_directory(tmp_path):
    for arguments, expected in [(['--help'], 'Commands:'),
                                (['benchmark', '--help'], '--models'),
                                (['verify', '--help'], '--speech')]:
        result = subprocess.run([sys.executable, str(ROOT / 'run_ultron.py'), *arguments],
                                cwd=tmp_path, env=clean_env(), capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        assert expected in result.stdout
    result = subprocess.run([sys.executable, str(ROOT / 'run_ultron.py'), 'not-a-command'],
                            cwd=tmp_path, env=clean_env(), capture_output=True, text=True, timeout=20)
    assert result.returncode == 2


def test_legacy_verification_wrapper_from_unrelated_directory(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / 'verify_ultron.py'), '--help'],
                            cwd=tmp_path, env=clean_env(), capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert '--speech' in result.stdout


def test_checkout_data_paths_are_preserved(monkeypatch, tmp_path):
    monkeypatch.delenv('ULTRON_PROJECT_ROOT', raising=False)
    monkeypatch.chdir(tmp_path)
    assert project_root() == ROOT
    assert memory_db.DB_PATH == ROOT / 'ultron_memory.db'
    assert start_ultron.ROOT == ROOT
    monkeypatch.setenv('ULTRON_PROJECT_ROOT', str(tmp_path))
    assert project_root() == tmp_path


def test_component_runner_uses_canonical_module(monkeypatch):
    calls = []
    monkeypatch.setattr(start_ultron.runpy, 'run_module', lambda module, **kw: calls.append((module, kw)))
    monkeypatch.setattr('builtins.input', lambda _: '')
    monkeypatch.setattr(start_ultron.os, 'chdir', lambda _: None)
    monkeypatch.setattr(start_ultron.sys, 'argv', ['test'])
    assert start_ultron._run_component('voice_listener') == 0
    assert calls == [('ultron.agents.voice_listener', {'run_name': '__main__'})]


def test_running_components_recognizes_package_commands():
    from types import SimpleNamespace
    processes = [SimpleNamespace(info={'cwd': str(ROOT), 'cmdline': command}) for command in [
        ['python', str(ROOT / 'run_ultron.py'), 'brain_agent'],
        ['python', '-m', 'ultron.agents.voice_listener'],
        ['python', str(ROOT / 'run_ultron.py'), 'send', 'action_daemon']]]
    assert start_ultron.running_components(ROOT, processes) == {'brain_agent', 'voice_listener'}
