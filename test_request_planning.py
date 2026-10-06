import pytest
from ultron_control.request_planning import explicit_launch_plan, PlanClarification


def names(calls):
    return [call['function']['arguments'].get('app_name') for call in calls if call['function']['name'] == 'open_application']


def test_real_multi_app_failure_has_all_four_actions():
    plan = explicit_launch_plan('Ok, can you open file explorer perplexity notion and search on youtube quantum computers.')
    assert names(plan) == ['File Explorer', 'Perplexity', 'Notion']
    assert len(plan) == 4
    assert plan[-1]['function']['arguments'] == {'target': 'youtube', 'query': 'quantum computers', 'count': 1}


@pytest.mark.parametrize('prompt', ['Open calculator.', 'Can you open calculator for me?', 'Can you do me a favor and open calculator?', 'Please launch calc!', 'Okay, please open calculator.'])
def test_polite_single_application(prompt):
    assert names(explicit_launch_plan(prompt)) == ['Calculator']


@pytest.mark.parametrize('prompt', ['Open Calculator, File Explorer, and Microsoft Edge.', 'Open calculator and file explorer and edge.', 'Open calculator file explorer edge.'])
def test_lists_and_longest_names(prompt):
    assert names(explicit_launch_plan(prompt)) == ['Calculator', 'File Explorer', 'Microsoft Edge']


def test_search_query_names_are_not_actions():
    plan = explicit_launch_plan('Open calculator and search on youtube how to use notion and perplexity.')
    assert names(plan) == ['Calculator']
    assert plan[1]['function']['arguments']['query'] == 'how to use notion and perplexity'


@pytest.mark.parametrize('prompt', ['Yes.', 'Do you hear me?', 'Do not open calculator.', 'If I ask, open calculator.', 'Open calculator unless I say stop.', 'How do I open calculator?'])
def test_other_intents_are_not_deterministic_launches(prompt):
    assert explicit_launch_plan(prompt) is None


@pytest.mark.parametrize('prompt', ['Open calculator mysteryapp notion.', 'Open calculator and delete files.', 'Open calculator,'])
def test_partial_or_unsupported_list_never_returns_partial_plan(prompt):
    with pytest.raises(PlanClarification):
        explicit_launch_plan(prompt)


def test_duplicate_launch_is_preserved():
    assert names(explicit_launch_plan('Open calculator and calculator.')) == ['Calculator', 'Calculator']


def test_uncatalogued_application_keeps_general_planner():
    assert explicit_launch_plan('Open my custom application.') is None


def test_actual_garbled_first_target_does_not_fall_back():
    with pytest.raises(PlanClarification):
        explicit_launch_plan('Open Perplexory Notion, task manager, search on youtube, quantum computers and also open file explorer.')


def test_model_cannot_insert_edge_from_history():
    from ultron_control.request_planning import validate_application_targets
    assert validate_application_targets('Open Perplexory Notion, task manager, search on youtube, quantum computers and also open file explorer.', [
        {'function': {'name': 'open_application', 'arguments': {'app_name': 'Microsoft Edge'}}}
    ])


def test_model_coverage_detects_omitted_catalog_application():
    from ultron_control.request_planning import validate_application_targets
    calls = [{'function': {'name': 'open_application', 'arguments': {'app_name': 'Notion'}}}]
    assert 'perplexity' in validate_application_targets('So I would like you to open notion as well as perplexity.', calls)


def test_alias_grounding_preserves_chrome_and_search_text_is_not_an_app_request():
    from ultron_control.request_planning import validate_application_targets
    calls = [{'function': {'name': 'open_application', 'arguments': {'app_name': 'Google Chrome'}}}]
    assert validate_application_targets('Open chrome and search on youtube how to use notion.', calls) is None


def test_launch_clause_after_search_is_checked():
    from ultron_control.request_planning import validate_application_targets
    calls = [{'function': {'name': 'open_application', 'arguments': {'app_name': 'Notion'}}}]
    assert 'file explorer' in validate_application_targets('Open notion and search youtube quantum computers and also open file explorer.', calls)


def test_query_application_name_cannot_authorize_app_launch():
    from ultron_control.request_planning import validate_application_targets
    calls = [{'function': {'name': 'open_application', 'arguments': {'app_name': 'Notion'}}}]
    assert validate_application_targets('Search youtube for how to open Notion.', calls)


def test_negated_launch_does_not_authorize_model_action():
    from ultron_control.request_planning import validate_application_targets
    calls = [{'function': {'name': 'open_application', 'arguments': {'app_name': 'Notion'}}}]
    assert validate_application_targets('Do not open Notion.', calls)


@pytest.mark.parametrize('target', ['ForzaHorizon6', 'Forza Horizon 6', 'ForzaHorizon6.exe'])
def test_cosmetic_game_name_spacing_preserves_current_target(target):
    from ultron_control.request_planning import validate_application_targets
    calls = [{'function': {'name': 'open_application', 'arguments': {'app_name': target}}}]
    assert validate_application_targets('Can you launch the Forza Horizon 6 game?', calls) is None


def test_game_version_is_not_fuzzy_matched():
    from ultron_control.request_planning import validate_application_targets
    calls = [{'function': {'name': 'open_application', 'arguments': {'app_name': 'ForzaHorizon5'}}}]
    assert validate_application_targets('Can you launch Forza Horizon 6?', calls)


def test_drive_request_is_grounded_but_does_not_invent_a_path():
    from ultron_control.request_planning import validate_application_targets
    calls = [{'function': {'name': 'open_application', 'arguments': {'app_name': 'ForzaHorizon6'}}}]
    assert validate_application_targets('Can you access my G drive and execute the Forza Horizon 6.exe game?', calls) is None
    assert 'path' not in calls[0]['function']['arguments']


def test_unrequested_protocol_invalidates_whole_plan():
    from ultron_control.request_planning import validate_application_targets
    calls = [{'function': {'name': 'activate_protocol', 'arguments': {'protocol': 'gaming_mode'}}}]
    assert validate_application_targets('Open Perplexor in Ocean and task manager.', calls)
    assert validate_application_targets('Activate gaming mode.', calls) is None


def test_negated_or_quoted_protocol_does_not_authorize_activation():
    from ultron_control.request_planning import validate_application_targets
    calls = [{'function': {'name': 'activate_protocol', 'arguments': {'protocol': 'gaming_mode'}}}]
    assert validate_application_targets('Do not activate gaming mode.', calls)
    assert validate_application_targets('Search youtube for how to start gaming mode.', calls)
