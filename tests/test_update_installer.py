"""Source updates must refuse incompatible versions before changing files."""
import json
from pathlib import Path

import pytest
from tools.install_update import install, digest


def bundle(tmp_path):
    source = tmp_path / 'update'; (source / 'files').mkdir(parents=True)
    target = tmp_path / 'project'; target.mkdir()
    manifest = {}
    for name in ['one.py', 'two.py']:
        old = b'old\n'; new = b'new\n'
        (target / name).write_bytes(old)
        (source / 'files' / name).write_bytes(new)
        manifest[name] = {'old': digest(old), 'new': digest(new)}
    (source / 'manifest.json').write_text(json.dumps(manifest))
    return source, target


def test_incompatible_second_file_changes_nothing(tmp_path):
    source, target = bundle(tmp_path)
    (target / 'two.py').write_text('local modification')
    with pytest.raises(ValueError, match='Unexpected local version'): install(source, target)
    assert (target / 'one.py').read_bytes() == b'old\n'
    assert (target / 'two.py').read_text() == 'local modification'


def test_failed_second_replace_restores_first_file(tmp_path, monkeypatch):
    import tools.install_update as updater
    source, target = bundle(tmp_path)
    replace = updater.os.replace
    def failure(temporary, destination):
        if Path(destination).name == 'two.py':
            raise OSError('simulated disk error')
        replace(temporary, destination)
    monkeypatch.setattr(updater.os, 'replace', failure)
    with pytest.raises(OSError): install(source, target)
    assert (target / 'one.py').read_bytes() == b'old\n'
    assert (target / 'two.py').read_bytes() == b'old\n'


def test_backup_idempotence_and_windows_line_endings(tmp_path):
    source, target = bundle(tmp_path)
    (target / 'one.py').write_bytes(b'old\r\n')
    backup = install(source, target)
    assert (backup / 'one.py').read_bytes() == b'old\r\n'
    assert (target / 'one.py').read_bytes() == b'new\n'
    assert install(source, target) is None


def test_corrupted_payload_is_rejected_before_mutation(tmp_path):
    source, target = bundle(tmp_path)
    (source / 'files' / 'two.py').write_text('corrupted')
    with pytest.raises(ValueError, match='integrity'): install(source, target)
    assert (target / 'one.py').read_bytes() == b'old\n'


def test_manifest_cannot_escape_checkout(tmp_path):
    source, target = bundle(tmp_path)
    (source / 'manifest.json').write_text(json.dumps({'../external.py': {'old': None, 'new': 'unused'}}))
    with pytest.raises(ValueError, match='Unsafe manifest'): install(source, target)
