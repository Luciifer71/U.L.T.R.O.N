from __future__ import annotations

import asyncio

from brain_agent import (
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
        monkeypatch.setattr("brain_agent.update_task", lambda *args, **kwargs: None)

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
        "brain_agent.os.listdir",
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


def test_strong_fuzzy_script_match_is_still_allowed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "brain_agent.os.listdir",
        lambda _: [
            "audio_listen.py",
            "action_daemon.py",
        ],
    )

    assert resolve_script_filename(
        "audio lesson.py",
        str(tmp_path),
    ) == "audio_listen.py"
