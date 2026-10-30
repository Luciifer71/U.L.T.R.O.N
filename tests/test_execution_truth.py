from __future__ import annotations

import asyncio

from ultron.agents.brain_agent import (
    PendingAction,
    UltronBrain,
    resolve_script_filename,
)


class FakeCapabilityResult:
    def __init__(self, success: bool, message: str, data=None, error=None):
        self.success = success
        self.message = message
        self.data = data or {}
        self.error = error


def bare_brain() -> UltronBrain:
    brain = object.__new__(UltronBrain)
    brain.execution_ledger = {}
    brain.last_replay_plan = None
    brain.history = [{"role": "system", "content": "test"}]
    return brain


def test_execution_response_does_not_claim_uri_verification() -> None:
    brain = bare_brain()
    brain.execution_ledger["task"] = [
        {
            "name": "open_website:https://www.youtube.com/results?search_query=quantum+computers",
            "success": True,
            "message": "Windows accepted the URI request.",
            "error": None,
            "state": "dispatched",
            "verification": "not_observable",
            "verificationReason": "Final browser handling cannot be observed.",
        }
    ]

    response = brain._compose_execution_response("task")

    assert "Dispatched: YouTube search." == response
    assert "opened" not in response.lower()
    assert "verified" not in response.lower()


def test_execution_response_reports_verified_application() -> None:
    brain = bare_brain()
    brain.execution_ledger["task"] = [
        {
            "name": "open_application:Notion",
            "success": True,
            "message": "Notion opened successfully.",
            "error": None,
            "state": None,
            "verification": {"running": True},
        }
    ]

    response = brain._compose_execution_response("task")

    assert response == "Opened and verified: Notion."


def test_execution_response_reports_partial_failure() -> None:
    brain = bare_brain()
    brain.execution_ledger["task"] = [
        {
            "name": "open_application:Notion",
            "success": True,
            "message": "Notion opened successfully.",
            "error": None,
            "state": None,
            "verification": {"running": True},
        },
        {
            "name": "open_application:Missing App",
            "success": False,
            "message": "Could not open 'Missing App'.",
            "error": "Application not found.",
            "state": None,
            "verification": None,
        },
    ]

    response = brain._compose_execution_response("task")

    assert "Opened and verified: Notion." in response
    assert "Could not complete: Missing App (Application not found.)." in response


def test_pending_action_ledger_records_capability_result(monkeypatch) -> None:
    async def run():
        brain = bare_brain()

        async def publish_visual(*args, **kwargs):
            return None

        brain._publish_visual = publish_visual
        monkeypatch.setattr("ultron.agents.brain_agent.update_task", lambda *args, **kwargs: None)

        async def action():
            return FakeCapabilityResult(
                True,
                "YouTube search dispatched.",
                data={
                    "state": "dispatched",
                    "verification": "not_observable",
                    "verificationReason": "URI handler outcome is not observable.",
                },
            )

        ok, error = await brain._run_pending_actions(
            [
                PendingAction(
                    name="open_website:https://www.youtube.com/results?search_query=test",
                    execute=action,
                )
            ],
            "task",
        )

        assert ok is True
        assert error is None
        assert brain.execution_ledger["task"][0]["success"] is True
        assert (
            brain.execution_ledger["task"][0]["verification"]
            == "not_observable"
        )

    asyncio.run(run())


def test_missing_script_is_not_fuzzy_matched(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "ultron.agents.brain_agent.os.listdir",
        lambda _: [
            "ollama_runtime.py",
            "brain_agent.py",
        ],
    )

    assert resolve_script_filename(
        "launch_game.py",
        str(tmp_path),
    ) is None


def test_normalized_existing_script_still_resolves(tmp_path) -> None:
    (tmp_path / "voice_listener.py").write_text("", encoding="utf-8")

    assert resolve_script_filename(
        "voice listener",
        str(tmp_path),
    ) == "voice_listener.py"


def test_similar_script_name_is_not_execution_authorization(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "ultron.agents.brain_agent.os.listdir",
        lambda _: [
            "audio_listen.py",
            "action_daemon.py",
        ],
    )

    assert resolve_script_filename(
        "audio lesson.py",
        str(tmp_path),
    ) is None


def test_missing_tool_call_retries_and_stages_without_executing(monkeypatch):
    async def run():
        brain = bare_brain()
        calls = []
        async def chat(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return {"message": {"content": "I opened Calculator."}}
            return {"message": {"tool_calls": [{"function": {
                "name": "open_application", "arguments": {"app_name": "Calculator"}
            }}]}}
        from types import SimpleNamespace
        brain.ollama = SimpleNamespace(chat=chat)
        brain.capabilities = SimpleNamespace(open_resource=lambda *a, **kw: None)
        async def visual(*a, **kw):
            pass
        brain._publish_visual = visual
        monkeypatch.setattr("ultron.agents.brain_agent.create_task", lambda *a, **kw: None)
        reply, actions = await brain.process_intent("I would like you to open calculator.", "retry-task")
        assert len(calls) == 2
        assert all("tools" in call for call in calls)
        assert len(actions) == 1
        assert actions[0].name == "open_application:Calculator"
        assert brain.execution_ledger == {}
        assert brain.last_plan_error is None
    asyncio.run(run())


def test_missing_plan_stops_after_one_retry_without_synthesis(monkeypatch):
    async def run():
        brain = bare_brain()
        calls = []
        async def chat(**kwargs):
            calls.append(kwargs)
            return {"message": {"content": "I opened Calculator."}}
        from types import SimpleNamespace
        brain.ollama = SimpleNamespace(chat=chat)
        async def visual(*a, **kw):
            pass
        brain._publish_visual = visual
        monkeypatch.setattr("ultron.agents.brain_agent.create_task", lambda *a, **kw: None)
        reply, actions = await brain.process_intent("I would like you to open calculator.", "failed-plan")
        assert len(calls) == 2
        assert actions == []
        assert "could not produce" in reply
        assert brain.last_plan_error
    asyncio.run(run())


def test_explicit_multi_app_plan_stages_every_target_without_llm(monkeypatch):
    async def run():
        from types import SimpleNamespace
        brain = bare_brain()
        async def unexpected_chat(**kwargs):
            raise AssertionError('Explicit complete launch list must not require model inference')
        brain.ollama = SimpleNamespace(chat=unexpected_chat)
        brain.capabilities = SimpleNamespace(open_resource=lambda *a, **kw: None)
        async def visual(*a, **kw):
            pass
        brain._publish_visual = visual
        monkeypatch.setattr('ultron.agents.brain_agent.create_task', lambda *a, **kw: None)
        _, actions = await brain.process_intent('Ok, can you open file explorer perplexity notion and search on youtube quantum computers.', 'complete-plan')
        assert [action.name for action in actions] == [
            'open_application:File Explorer', 'open_application:Perplexity',
            'open_application:Notion',
            'open_website:https://www.youtube.com/results?search_query=quantum+computers',
        ]
        assert brain.execution_ledger == {}
        assert brain.last_plan_error is None
    asyncio.run(run())


def test_partial_explicit_list_stages_nothing(monkeypatch):
    async def run():
        brain = bare_brain()
        async def visual(*a, **kw):
            pass
        brain._publish_visual = visual
        _, actions = await brain.process_intent('Open calculator mysteryapp notion.', 'ambiguous-plan')
        assert actions == []
        assert brain.last_plan_error
    asyncio.run(run())


def test_actual_garbled_request_never_reaches_model_or_execution():
    async def run():
        brain = bare_brain()
        async def visual(*args, **kwargs):
            pass
        brain._publish_visual = visual
        reply, actions = await brain.process_intent('Open Perplexory Notion, task manager, search on youtube, quantum computers and also open file explorer.', 'garbled')
        assert actions == []
        assert 'No actions were started' in reply
        assert brain.last_plan_error
        assert brain.execution_ledger == {}
    asyncio.run(run())


def test_model_inserted_app_is_rejected_before_staging(monkeypatch):
    async def run():
        from types import SimpleNamespace
        brain = bare_brain()
        async def visual(*args, **kwargs):
            pass
        async def chat(**kwargs):
            return {'message': {'tool_calls': [{'function': {'name': 'open_application', 'arguments': {'app_name': 'Microsoft Edge'}}}]}}
        brain._publish_visual = visual
        brain.ollama = SimpleNamespace(chat=chat)
        monkeypatch.setattr('ultron.agents.brain_agent.create_task', lambda *a, **kw: None)
        reply, actions = await brain.process_intent('I would like you to open Notion.', 'inserted')
        assert actions == []
        assert 'not named' in reply
        assert brain.last_plan_error
        assert brain.last_replay_plan is None
    asyncio.run(run())


def test_failed_action_does_not_contaminate_next_conversation(monkeypatch):
    from types import SimpleNamespace
    async def run():
        brain = bare_brain()
        async def visual(*args, **kwargs):
            pass
        brain._publish_visual = visual
        monkeypatch.setattr('ultron.agents.brain_agent.create_task', lambda *a, **kw: None)
        async def chat(**kwargs):
            assert all('mysteryapp' not in m.get('content', '') for m in kwargs['messages'])
            return {'message': {'content': 'What would you like to discuss?'}}
        brain.ollama = SimpleNamespace(chat=chat)
        _, actions = await brain.process_intent('Open calculator mysteryapp notion.', 'failed')
        assert not actions
        assert len(brain.history) == 1
        reply, actions = await brain.process_intent('We have time.', 'conversation')
        assert reply == 'What would you like to discuss?'
        assert [m['role'] for m in brain.history] == ['system', 'user', 'assistant']
    asyncio.run(run())


def test_restart_keeps_facts_but_does_not_restore_mixed_chat_log(monkeypatch):
    monkeypatch.setattr('ultron.agents.brain_agent.get_all_facts', lambda: [{'key': 'name', 'value': 'Krish'}])
    brain = object.__new__(UltronBrain)
    brain.refresh_system_prompt()
    assert len(brain.history) == 1
    assert 'Krish' in brain.history[0]['content']


def test_interrupted_turn_restores_previous_conversation():
    async def run():
        brain = bare_brain()
        async def interrupted(prompt, task_id):
            brain.history.append({'role': 'user', 'content': prompt})
            raise asyncio.CancelledError
        brain._process_intent = interrupted
        try:
            await brain.process_intent('anything', 'cancelled')
        except asyncio.CancelledError:
            pass
        assert brain.history == [{'role': 'system', 'content': 'test'}]
    asyncio.run(run())


def test_batch_preflight_failure_starts_no_actions(monkeypatch):
    async def run():
        brain = bare_brain()
        executed = []
        checked = []
        async def prepare_ok():
            checked.append('calculator')
        async def prepare_missing():
            checked.append('missing')
            raise ValueError('Application not installed')
        actions = [PendingAction('open_application:Calculator', lambda: executed.append('calculator'), preflight=prepare_ok),
                   PendingAction('open_application:Missing', lambda: executed.append('missing'), preflight=prepare_missing)]
        ok, error = await brain._run_pending_actions(actions, 'preflight')
        assert not ok and 'No actions were started' in error
        assert checked == ['calculator', 'missing'] and executed == []
        assert brain.execution_ledger['preflight'][0]['state'] == 'preflight_failed'
        assert 'No actions were started' in brain._compose_execution_response('preflight')
    asyncio.run(run())


def test_batch_preflight_completes_before_first_execution(monkeypatch):
    async def run():
        brain = bare_brain()
        events = []
        async def visual(*a, **kw):
            pass
        brain._publish_visual = visual
        monkeypatch.setattr('ultron.agents.brain_agent.update_task', lambda *a, **kw: None)
        monkeypatch.setattr('ultron.agents.brain_agent.EXECUTION_MIN_HOLD_SEC', 0)
        actions = [PendingAction('open_application:' + name,
                    lambda n=name: events.append('execute:' + n),
                    preflight=lambda n=name: events.append('resolve:' + n)) for name in ['Calculator', 'File Explorer']]
        ok, error = await brain._run_pending_actions(actions, 'prepared')
        assert ok and error is None
        assert events == ['resolve:Calculator', 'resolve:File Explorer', 'execute:Calculator', 'execute:File Explorer']
    asyncio.run(run())


def test_youtube_success_requires_playing_evidence():
    brain = bare_brain()
    brain.execution_ledger['song'] = [{
        'name': 'play_youtube:Song by Artist', 'success': True,
        'state': 'verified', 'verification': {'playing': True},
    }]
    assert brain._compose_execution_response('song') == 'YouTube playback verified: Song by Artist.'
    brain.execution_ledger['song'][0].update(success=False, error='Ads or consent blocked verification.')
    reply = brain._compose_execution_response('song')
    assert 'Could not complete' in reply and 'playback verified' not in reply
