import json
import sys
import zipfile

from ultron.cli.collect_ultron_report import make_bundle, redact
from ultron.control.session_logs import capture_console


def test_console_output_and_errors_saved_with_streams_restored(tmp_path, capsys):
    original = sys.stdout
    with capture_console(tmp_path, 'brain_agent'):
        print('task result')
        print('failure details', file=sys.stderr)
    assert sys.stdout is original
    captured = capsys.readouterr()
    assert 'task result' in captured.out and 'failure details' in captured.err
    log = (tmp_path / 'runtime/logs/brain_agent.log').read_text()
    assert 'task result' in log and 'failure details' in log and '[SESSION START]' in log


def test_bundle_allowlist_redaction_and_missing_components(tmp_path):
    logs = tmp_path / 'runtime/logs'
    logs.mkdir(parents=True)
    (logs / 'brain_agent.log').write_text('API_KEY=private-value\nOpen calculator\nhttps://example.com/?TrustedClientToken=abc&x=1')
    (tmp_path / '.env').write_text('TOP_SECRET=value')
    (logs / 'private.db').write_text('private database')
    report = tmp_path / 'report.json'
    report.write_text('{"regression_tests":{"status":"passed"}}')
    output = tmp_path / 'support.zip'
    manifest = make_bundle(tmp_path, report, output)
    assert len(manifest['missing']) == 2
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {'diagnostics.json', 'logs/brain_agent.log', 'manifest.json', 'READ_ME.txt'}
        text = archive.read('logs/brain_agent.log').decode()
        assert 'private-value' not in text and 'TrustedClientToken=abc' not in text
        assert 'Open calculator' in text
        assert json.loads(archive.read('diagnostics.json'))['regression_tests']['status'] == 'passed'


def test_redacts_url_credentials_and_windows_user():
    value = redact(r'nats://user:password@localhost C:\Users\Krish\file.txt')
    assert 'user:password' not in value and 'Krish' not in value
