import json
from pathlib import Path
import sys

import resource_cli
from ultron_resources.catalog import PathPolicy, ResourceCatalog
from ultron_resources.service import ResourceService


def service(tmp_path, monkeypatch):
    root = tmp_path / 'files'; root.mkdir()
    result = ResourceService(ResourceCatalog(tmp_path / 'catalog.db', PathPolicy([root])))
    monkeypatch.setattr(resource_cli, 'create_service', lambda: result)
    return result, root


def test_incomplete_index_has_distinct_nonzero_exit(tmp_path, monkeypatch, capsys):
    _, root = service(tmp_path, monkeypatch)
    (root / 'report.txt').write_text('text')
    monkeypatch.setattr(sys, 'argv', ['resource_cli.py', 'index', '--max-entries', '1'])
    assert resource_cli.main() == 2
    assert json.loads(capsys.readouterr().out)['complete'] is False


def test_cli_reports_ambiguity_without_execution(tmp_path, monkeypatch, capsys):
    engine, root = service(tmp_path, monkeypatch)
    for name in ['one', 'two']:
        folder = root / name; folder.mkdir(); (folder / 'game.exe').write_text('placeholder')
    engine.catalog.index(root)
    monkeypatch.setattr(sys, 'argv', ['resource_cli.py', 'launch', 'game'])
    assert resource_cli.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report['success'] is False and len(report['candidates']) == 2


def test_cli_returns_actual_script_exit_failure(tmp_path, monkeypatch, capsys):
    _, root = service(tmp_path, monkeypatch)
    script = root / 'failure.py'; script.write_text('raise SystemExit(4)')
    monkeypatch.setattr(sys, 'argv', ['resource_cli.py', 'run', str(script)])
    assert resource_cli.main() == 1
    assert json.loads(capsys.readouterr().out)['exit_code'] == 4


def test_cli_read_is_explicit_and_bounded(tmp_path, monkeypatch, capsys):
    _, root = service(tmp_path, monkeypatch)
    path = root / 'notes.txt'; path.write_text('hello')
    monkeypatch.setattr(sys, 'argv', ['resource_cli.py', 'read', str(path)])
    assert resource_cli.main() == 0
    assert json.loads(capsys.readouterr().out)['text'] == 'hello'
