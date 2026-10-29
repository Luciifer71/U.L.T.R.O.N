import pytest
from ultron_resources.native_apps import ExactApplicationDiscovery
from ultron_control.application_discovery import ApplicationAmbiguous
from ultron_control.resource_discovery import ResourceDiscovery


def test_spelling_or_game_number_never_selects_similar_installed_application():
    discovery = ExactApplicationDiscovery()
    assert discovery._best_start_app_match('forza horizon 6', [('Forza Horizon 5', 'game5')]) is None
    assert discovery._best_start_app_match('perplexor', [('Perplexity', 'app')]) is None
    assert discovery._best_start_app_match('forza horizon 6', [('ForzaHorizon6', 'game6')]) == ('ForzaHorizon6', 'game6')


def test_same_name_with_different_app_identity_is_ambiguous():
    with pytest.raises(ApplicationAmbiguous):
        ExactApplicationDiscovery()._best_start_app_match('Example', [('Example', 'one'), ('Example', 'two')])


def test_exact_start_identity_is_used_for_packaged_app(monkeypatch):
    discovery = ExactApplicationDiscovery()
    app = {'name': 'Publisher.App', 'packageFamilyName': 'Publisher.App_family', 'applicationId': 'Main', 'applicationDisplayName': 'ms-resource:Title'}
    monkeypatch.setattr(discovery, 'list_packaged_apps', lambda: [app])
    result = discovery._resolve_packaged_app('notion', [('Notion', 'Publisher.App_family!Main')])
    assert result.app_id == 'Publisher.App_family!Main'


def test_similar_packaged_app_name_is_not_accepted(monkeypatch):
    discovery = ExactApplicationDiscovery()
    app = {'name': 'Game5', 'packageFamilyName': 'family', 'applicationId': 'Main', 'applicationDisplayName': 'Forza Horizon 5'}
    monkeypatch.setattr(discovery, 'list_packaged_apps', lambda: [app])
    assert discovery._resolve_packaged_app('Forza Horizon 6', []) is None


def test_microsoft_store_uses_its_registered_system_protocol():
    resolved = ResourceDiscovery().resolve('Microsoft Store')
    assert resolved.uri == 'ms-windows-store:'
    assert resolved.kind == 'uri'
