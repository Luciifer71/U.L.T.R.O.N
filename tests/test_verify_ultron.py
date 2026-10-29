from types import SimpleNamespace
import verify_ultron


def setup_runner(monkeypatch, tmp_path):
    monkeypatch.setattr(verify_ultron, '__file__', str(tmp_path / 'verify_ultron.py'))
    monkeypatch.setattr(verify_ultron.sys, 'argv', ['verify_ultron.py'])
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 'test_example.py').write_text('')


def test_runner_propagates_failed_tests(monkeypatch, tmp_path):
    setup_runner(monkeypatch, tmp_path)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(verify_ultron.subprocess, 'run', run)
    assert verify_ultron.main() == 1
    assert len(calls) == 1
    assert calls[0][0] == verify_ultron.sys.executable
    assert 'tests/test_example.py' in calls[0]


def test_runner_rejects_empty_suite(monkeypatch, tmp_path):
    setup_runner(monkeypatch, tmp_path)
    (tmp_path / 'tests' / 'test_example.py').unlink()
    assert verify_ultron.main() == 2


def test_runner_propagates_failed_speech_probe(monkeypatch, tmp_path):
    setup_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(verify_ultron.sys, 'argv', ['verify_ultron.py', '--speech'])
    results = iter([0, 1])
    monkeypatch.setattr(verify_ultron.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=next(results)))
    assert verify_ultron.main() == 1

def test_runner_discovers_nested_tests_without_root_scratch_files(monkeypatch, tmp_path):
    setup_runner(monkeypatch, tmp_path)
    nested = tmp_path / 'tests' / 'integration'
    nested.mkdir()
    (nested / 'test_nested.py').write_text('')
    (tmp_path / 'test_private_scratch.py').write_text('')
    calls = []
    monkeypatch.setattr(verify_ultron.subprocess, 'run', lambda command, **kw: calls.append(command) or SimpleNamespace(returncode=0))
    assert verify_ultron.main() == 0
    assert 'tests/integration/test_nested.py' in calls[0]
    assert 'test_private_scratch.py' not in calls[0]
