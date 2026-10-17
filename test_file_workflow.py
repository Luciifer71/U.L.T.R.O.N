from types import SimpleNamespace
from pathlib import Path

import pytest

from ultron_resources import file_workflow as workflow
from ultron_resources.catalog import PathPolicy, ResourceCatalog, ResourceError, AmbiguousResource
from ultron_resources.service import ResourceService
from ultron_control.request_planning import explicit_file_plan, validate_application_targets


def service_for(tmp_path, monkeypatch):
    folder = tmp_path / 'Downloads'
    folder.mkdir()
    opened = []
    adapter = SimpleNamespace(open=lambda path, editor=None: opened.append(Path(path)))
    service = ResourceService(ResourceCatalog(tmp_path / 'catalog.db', PathPolicy([tmp_path])), adapter)
    monkeypatch.setattr(workflow, 'known_folder', lambda name: folder)
    return service, folder, opened


@pytest.mark.parametrize("filename", ["Supergirl.2026.1080p.mkv", "Supergirl_2026_1080p.mkv", "SUPERGIRL-2026.MP4"])
def test_unique_media_match_dispatches_without_catalog_index(tmp_path, monkeypatch, filename):
    service, folder, opened = service_for(tmp_path, monkeypatch)
    movie = folder / filename
    movie.write_bytes(b'test fixture')
    selected = workflow.prepare_file(service, 'Supergirl', 'downloads', media_only=True)
    assert opened == []
    result = workflow.open_prepared_file(service, selected)
    assert opened == [movie]
    assert result.state == 'dispatched' and result.data['verification'] == 'not_observable'


@pytest.mark.parametrize('name', ['Supergirl2.mp4', 'super well.mp4', 'Supergirl.mp4.exe', 'Supergirl.ps1'])
def test_unmatched_or_executable_target_never_opens(tmp_path, monkeypatch, name):
    service, folder, opened = service_for(tmp_path, monkeypatch)
    (folder / name).write_bytes(b'test')
    with pytest.raises(ResourceError):
        workflow.prepare_file(service, 'Supergirl', 'downloads', media_only=True)
    assert opened == []


def test_duplicate_media_requires_selection(tmp_path, monkeypatch):
    service, folder, opened = service_for(tmp_path, monkeypatch)
    for name in ['Supergirl.2026.mp4', 'Supergirl.2025.mkv']:
        (folder / name).write_bytes(b'test')
    with pytest.raises(AmbiguousResource) as error:
        workflow.prepare_file(service, 'Supergirl', 'downloads', media_only=True)
    assert len(error.value.candidates) == 2 and opened == []


def test_incomplete_scan_cannot_claim_unique_match(tmp_path, monkeypatch):
    service, folder, opened = service_for(tmp_path, monkeypatch)
    (folder / 'Supergirl.mp4').write_bytes(b'test')
    (folder / 'another.txt').write_text('test')
    with pytest.raises(ResourceError, match='incomplete'):
        workflow.prepare_file(service, 'Supergirl', 'downloads', max_entries=1)
    assert opened == []


def test_changed_file_is_rejected_before_dispatch(tmp_path, monkeypatch):
    service, folder, opened = service_for(tmp_path, monkeypatch)
    path = folder / 'report.pdf'
    path.write_bytes(b'test')
    selected = workflow.prepare_file(service, 'report.pdf', 'downloads')
    path.write_bytes(b'changed file')
    with pytest.raises(ResourceError, match='changed'):
        workflow.open_prepared_file(service, selected)
    assert opened == []


def test_explicit_extension_is_not_corrected(tmp_path, monkeypatch):
    service, folder, opened = service_for(tmp_path, monkeypatch)
    (folder / 'report.pdf').write_bytes(b'test')
    with pytest.raises(ResourceError):
        workflow.prepare_file(service, 'report.docx', 'downloads')
    assert opened == []


def test_search_is_scoped_and_finds_nested_file(tmp_path, monkeypatch):
    service, folder, opened = service_for(tmp_path, monkeypatch)
    (tmp_path / 'Supergirl.mp4').write_bytes(b'outside scope')
    subfolder = folder / 'Movies'
    subfolder.mkdir()
    movie = subfolder / 'Supergirl.mp4'
    movie.write_bytes(b'test')
    selected = workflow.prepare_file(service, 'Supergirl', 'downloads', media_only=True)
    assert selected.path == movie and opened == []


@pytest.mark.parametrize('prompt', [
    'Play the movie Supergirl from my downloads folder.',
    'Okay, can you access my downloads folder and play the movie Supergirl?',
    'Can you play Supergirl in Downloads for me?',
])
def test_spoken_file_request_preserves_title_and_scope(prompt):
    calls = explicit_file_plan(prompt)
    assert calls == [{'function': {'name': 'find_and_open_file', 'arguments': {
        'query': 'Supergirl', 'folder': 'downloads', 'media_only': True}}}]
    assert validate_application_targets(prompt, calls) is None


@pytest.mark.parametrize('prompt', [
    'I hate the movie Supergirl.', 'Do not play Supergirl from Downloads.',
    'If I finish studying, play Supergirl from Downloads.',
    'Play Supergirl.', 'Search for how to play Supergirl from Downloads.',
])
def test_file_workflow_does_not_infer_missing_action_or_folder(prompt):
    assert explicit_file_plan(prompt) is None
    call = {'function': {'name': 'find_and_open_file', 'arguments': {'query': 'Supergirl', 'folder': 'downloads', 'media_only': True}}}
    assert validate_application_targets(prompt, [call])


def test_model_cannot_change_file_title_or_folder():
    calls = explicit_file_plan('Play Supergirl from Downloads.')
    calls[0]['function']['arguments']['folder'] = 'documents'
    assert validate_application_targets('Play Supergirl from Downloads.', calls)


def test_deadline_cannot_select_from_partial_search(tmp_path, monkeypatch):
    service, folder, opened = service_for(tmp_path, monkeypatch)
    (folder / 'Supergirl.mp4').write_bytes(b'test')
    times = iter([0, 5])
    monkeypatch.setattr(workflow.time, 'monotonic', lambda: next(times))
    with pytest.raises(ResourceError, match='incomplete'):
        workflow.prepare_file(service, 'Supergirl', 'downloads')
    assert opened == []


def test_unreadable_subfolder_prevents_partial_selection(tmp_path, monkeypatch):
    service, folder, opened = service_for(tmp_path, monkeypatch)
    (folder / 'Supergirl.mp4').write_bytes(b'test')
    nested = folder / 'private'
    nested.mkdir()
    original = workflow.os.scandir
    def scan(path):
        if Path(path) == nested:
            raise PermissionError('test access denied')
        return original(path)
    monkeypatch.setattr(workflow.os, 'scandir', scan)
    with pytest.raises(ResourceError, match='could not be completed'):
        workflow.prepare_file(service, 'Supergirl', 'downloads')
    assert opened == []


def test_play_request_cannot_select_document(tmp_path, monkeypatch):
    service, folder, opened = service_for(tmp_path, monkeypatch)
    (folder / 'Supergirl.pdf').write_bytes(b'test')
    with pytest.raises(ResourceError, match='No matching'):
        workflow.prepare_file(service, 'Supergirl', 'downloads', media_only=True)
    assert opened == []


def test_linked_file_is_not_selected(tmp_path, monkeypatch):
    service, folder, opened = service_for(tmp_path, monkeypatch)
    outside = tmp_path / 'outside.mp4'
    outside.write_bytes(b'test')
    try:
        (folder / 'Supergirl.mp4').symlink_to(outside)
    except OSError:
        pytest.skip('Symlink creation unavailable on this host')
    with pytest.raises(ResourceError, match='No matching'):
        workflow.prepare_file(service, 'Supergirl', 'downloads')
    assert opened == []
