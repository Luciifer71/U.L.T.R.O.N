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
