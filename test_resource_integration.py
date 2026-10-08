"""User request -> staged resource action -> real process -> execution evidence."""
import asyncio
from types import SimpleNamespace

import pytest

from brain_agent import UltronBrain
from ultron_control.request_planning import validate_application_targets, explicit_launch_plan
from ultron_resources.catalog import PathPolicy, ResourceCatalog
from ultron_resources.service import ResourceService


def call(operation, target, **options):
    return {'function': {'name': 'operate_resource', 'arguments': {'operation': operation, 'target': target, **options}}}


@pytest.mark.parametrize('prompt,tool', [
    ('Run example.py.', call('run_script', 'example.py')),
    ('Please read notes.txt.', call('read', 'notes.txt')),
    ('Open notes.txt in Notepad.', call('open', 'notes.txt', editor='Notepad')),
    ('Can you access my G drive and execute Forza Horizon 6?', call('launch', 'ForzaHorizon6', root='G:\\')),
    ('Run example.py with argument hello.', call('run_script', 'example.py', arguments=['hello'])),
])
def test_current_request_allows_literal_typed_operation(prompt, tool):
    assert validate_application_targets(prompt, [tool]) is None


@pytest.mark.parametrize('prompt,tool', [
    ('Do not run example.py.', call('run_script', 'example.py')),
    ('Why can you not execute example.py?', call('run_script', 'example.py')),
    ('Search for how to run example.py.', call('run_script', 'example.py')),
    ('If the download finishes, run example.py.', call('run_script', 'example.py')),
    ('Read example.py.', call('run_script', 'example.py')),
    ('Run example.py.', call('run_script', 'different.py')),
    ('Run example.py.', call('run_script', 'example.py', arguments=['--delete'])),
    ('Open notes.txt.', call('open', 'notes.txt', editor='Notepad')),
    ('Open notes.txt.', call('open', 'notes.txt', root='G:\\private')),
    ('Launch Forza Horizon 6.', call('launch', 'ForzaHorizon5')),
    ('Run example.py.', call('remove', 'example.py')),
    ('Read किताब.txt.', call('read', 'कताब.txt')),
])
def test_unrequested_operation_target_argument_or_scope_is_rejected(prompt, tool):
    assert validate_application_targets(prompt, [tool])


def test_editor_request_is_not_parsed_as_two_application_launches():
    assert explicit_launch_plan('Open notes.txt in Notepad.') is None


def make_brain(tmp_path, monkeypatch, model_calls):
    brain = object.__new__(UltronBrain)
    brain.execution_ledger = {}
    brain.last_replay_plan = None
    brain.history = [{'role': 'system', 'content': 'test'}]
    brain.resource_service = ResourceService(ResourceCatalog(tmp_path / 'catalog.db', PathPolicy([tmp_path])))
    async def chat(**kwargs):
        return {'message': {'content': '', 'tool_calls': model_calls}}
    async def visual(*args, **kwargs):
        pass
    brain.ollama = SimpleNamespace(chat=chat)
    brain._publish_visual = visual
    monkeypatch.setattr('brain_agent.create_task', lambda *a, **k: None)
    monkeypatch.setattr('brain_agent.update_task', lambda *a, **k: None)
    monkeypatch.setattr('brain_agent.EXECUTION_MIN_HOLD_SEC', 0)
    return brain


def test_polite_script_bypasses_model_and_preserves_target(tmp_path, monkeypatch):
    brain = make_brain(tmp_path, monkeypatch, [])
    async def forbidden_model(**kwargs):
        pytest.fail('Explicit polite script request must not reach the model')
    brain.ollama.chat = forbidden_model
    async def run():
        _, actions = await brain.process_intent('Okay, can you run Ultron smoke script?', 'polite')
        assert len(actions) == 1
        assert actions[0].name == 'operate_resource:run_script:Ultron smoke script'
    asyncio.run(run())


def test_model_extension_correction_never_stages_execution(tmp_path, monkeypatch):
    brain = make_brain(tmp_path, monkeypatch, [call('run_script', 'report.py')])
    async def run():
        _, actions = await brain.process_intent('Run report.py5.', 'extension')
        assert actions == []
    asyncio.run(run())


def test_script_is_staged_then_completed_from_real_exit_code(tmp_path, monkeypatch):
    script = tmp_path / 'sample.py'
    marker = tmp_path / 'ran.txt'
    script.write_text('from pathlib import Path; Path("ran.txt").write_text("done"); print("finished")')
    brain = make_brain(tmp_path, monkeypatch, [call('run_script', str(script))])
    async def run():
        _, actions = await brain.process_intent(f'Run {script}', 'task')
        assert len(actions) == 1
        assert not marker.exists()
        success, error = await brain._run_pending_actions(actions, 'task')
        assert success and error is None
        assert marker.read_text() == 'done'
        evidence = brain.execution_ledger['task'][0]
        assert evidence['exitCode'] == 0
        assert evidence['stdout'].strip() == 'finished'
        assert brain._compose_execution_response('task') == f'Completed: {script}.'
    asyncio.run(run())


def test_nonzero_script_never_produces_completion_claim(tmp_path, monkeypatch):
    script = tmp_path / 'failure.py'; script.write_text('raise SystemExit(9)')
    brain = make_brain(tmp_path, monkeypatch, [call('run_script', str(script))])
    async def run():
        _, actions = await brain.process_intent(f'Run {script}', 'task')
        success, error = await brain._run_pending_actions(actions, 'task')
        assert not success and '9' in error
        assert 'Could not complete' in brain._compose_execution_response('task')
        assert 'Completed:' not in brain._compose_execution_response('task')
    asyncio.run(run())


def test_missing_plan_does_not_invent_permission_restrictions(tmp_path, monkeypatch):
    brain = make_brain(tmp_path, monkeypatch, [])
    async def refusal(**kwargs):
        return {'message': {'content': 'I cannot access your files due to security restrictions.'}}
    brain.ollama.chat = refusal
    async def run():
        reply, actions = await brain.process_intent('Please execute my custom game.', 'task')
        assert not actions and brain.last_plan_error
        assert 'security restrictions' not in reply
        assert 'validated execution plan' in reply
    asyncio.run(run())


def test_duplicate_catalog_name_never_launches_a_candidate(tmp_path, monkeypatch):
    for folder in ['one', 'two']:
        directory = tmp_path / folder; directory.mkdir()
        (directory / 'game.exe').write_text('placeholder')
    brain = make_brain(tmp_path, monkeypatch, [call('launch', 'game')])
    brain.resource_service.catalog.index(tmp_path)
    def unexpected(*a, **kw):
        raise AssertionError('Ambiguous targets must not reach the OS adapter')
    brain.resource_service.adapter.launch = unexpected
    async def run():
        _, actions = await brain.process_intent('Launch game.', 'task')
        success, error = await brain._run_pending_actions(actions, 'task')
        assert not success and 'Multiple exact matches' in error
        assert 'Candidates:' in brain._compose_execution_response('task')
    asyncio.run(run())


def test_known_application_plan_still_uses_existing_broker(tmp_path, monkeypatch):
    brain = make_brain(tmp_path, monkeypatch, [])
    targets = []
    async def open_resource(target, **kwargs):
        targets.append(target)
        return SimpleNamespace(success=True, message='running', error=None, data={'verification': {'running': True}})
    brain.capabilities = SimpleNamespace(open_resource=open_resource)
    async def run():
        _, actions = await brain.process_intent('Open calculator.', 'task')
        assert not targets
        success, _ = await brain._run_pending_actions(actions, 'task')
        assert success and targets == ['Calculator']
        assert brain._compose_execution_response('task') == 'Opened and verified: Calculator.'
    asyncio.run(run())


def test_actual_spoken_script_runs_exact_catalog_name_without_model(tmp_path, monkeypatch):
    script = tmp_path / 'ultron_smoke_script.py'
    script.write_text('print("correct script")')
    brain = make_brain(tmp_path, monkeypatch, [])
    brain.resource_service.catalog.index(tmp_path)
    async def forbidden(**kwargs):
        raise AssertionError('This complete literal request must not invoke the model')
    brain.ollama.chat = forbidden
    async def run():
        _, actions = await brain.process_intent('run Ultron smoke script.', 'task')
        assert len(actions) == 1 and not brain.last_plan_error
        success, error = await brain._run_pending_actions(actions, 'task')
        assert success and error is None
        assert brain.execution_ledger['task'][0]['stdout'].strip() == 'correct script'
    asyncio.run(run())


def test_actual_misheard_editor_request_never_reaches_model(tmp_path, monkeypatch):
    brain = make_brain(tmp_path, monkeypatch, [])
    async def forbidden(**kwargs):
        raise AssertionError('Ambiguous editor request must stop before model selection')
    brain.ollama.chat = forbidden
    async def run():
        reply, actions = await brain.process_intent('Open Ultron smoke note and not pad.', 'task')
        assert not actions and brain.last_plan_error
        assert 'Notepad' in reply and 'Forza' not in reply
    asyncio.run(run())
