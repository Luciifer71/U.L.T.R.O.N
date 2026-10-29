import json
import zipfile

import ultron_acceptance as acceptance


def test_planning_contracts_include_garbled_speech_and_all_pass():
    rows = acceptance.planning_checks()
    assert len(rows) >= 10 and all(r['passed'] for r in rows)
    assert any('Annual pull' in r['prompt'] for r in rows)


def setup_acceptance(tmp_path, monkeypatch, status):
    monkeypatch.setattr(acceptance, 'ROOT', tmp_path)
    for name in ('brain_agent.py', 'ultron_control/request_planning.py', 'ultron_acceptance.py'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('source')
    monkeypatch.setattr(acceptance, 'run_regressions', lambda *a: ({'status': status}, 'test output'))
    monkeypatch.setattr(acceptance, 'build_report', lambda *a: {'scope': 'test'})


def test_default_acceptance_never_launches_apps_and_packages_results(tmp_path, monkeypatch):
    setup_acceptance(tmp_path, monkeypatch, 'passed')
    async def forbidden():
        raise AssertionError('Live checks were not requested')
    monkeypatch.setattr(acceptance, 'live_checks', forbidden)
    assert acceptance.main([]) == 0
    report = json.loads((tmp_path / 'runtime/acceptance/latest.json').read_text())
    assert report['live']['status'] == 'not_run' and report['manual_audio'] == 'unverified'
    bundle = next((tmp_path / 'runtime/support').glob('*.zip'))
    with zipfile.ZipFile(bundle) as archive:
        assert json.loads(archive.read('acceptance.json'))['status'] == 'passed'
        assert archive.read('diagnostic-console.txt') == b'test output'


def test_failed_offline_gate_blocks_live_actions_and_returns_failure(tmp_path, monkeypatch):
    setup_acceptance(tmp_path, monkeypatch, 'failed')
    async def forbidden():
        raise AssertionError('Offline failures must block live checks')
    monkeypatch.setattr(acceptance, 'live_checks', forbidden)
    assert acceptance.main(['--live-apps']) == 1
    report = json.loads((tmp_path / 'runtime/acceptance/latest.json').read_text())
    assert report['live']['status'] == 'blocked_by_offline_failure'

def test_regression_runner_fails_closed_when_suite_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(acceptance, 'ROOT', tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError('Do not fall back to unbounded pytest discovery')
    monkeypatch.setattr(acceptance.subprocess, 'run', forbidden)
    report, message = acceptance.run_regressions(tmp_path / 'results.xml')
    assert report['status'] == 'failed' and report['exit_code'] == 2
    assert 'No regression test files' in message


def test_regression_runner_uses_nested_test_directory(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(acceptance, 'ROOT', tmp_path)
    suite = tmp_path / 'tests' / 'integration'
    suite.mkdir(parents=True)
    (suite / 'test_example.py').write_text('')
    calls = []
    monkeypatch.setattr(acceptance.subprocess, 'run', lambda command, **kw: calls.append(command) or SimpleNamespace(returncode=0, stdout='', stderr=''))
    report, _ = acceptance.run_regressions(tmp_path / 'results.xml')
    assert report['status'] == 'passed'
    assert 'tests/integration/test_example.py' in calls[0]
