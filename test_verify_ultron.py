from types import SimpleNamespace
import verify_ultron


def setup_runner(monkeypatch, tmp_path):
    monkeypatch.setattr(verify_ultron, '__file__', str(tmp_path / 'verify_ultron.py'))
    monkeypatch.setattr(verify_ultron.sys, 'argv', ['verify_ultron.py'])
    (tmp_path / 'test_example.py').write_text('')


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
    assert 'test_example.py' in calls[0]


def test_runner_rejects_empty_suite(monkeypatch, tmp_path):
    setup_runner(monkeypatch, tmp_path)
    (tmp_path / 'test_example.py').unlink()
    assert verify_ultron.main() == 2


def test_runner_propagates_failed_speech_probe(monkeypatch, tmp_path):
    setup_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(verify_ultron.sys, 'argv', ['verify_ultron.py', '--speech'])
    results = iter([0, 1])
    monkeypatch.setattr(verify_ultron.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=next(results)))
    assert verify_ultron.main() == 1
