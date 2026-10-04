from __future__ import annotations

import memory_db


def test_task_memory_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(memory_db, "DB_PATH", tmp_path / "ultron_memory.db")
    memory_db.init_memory_db()

    memory_db.create_task("task-1", "Open Notion", status="thinking")
    memory_db.update_task(
        "task-1",
        "executing",
        event_message="Started application launch.",
        execution=[{"name": "open_application:Notion", "success": True}],
    )
    memory_db.update_task(
        "task-1",
        "completed",
        result_text="Opened and verified: Notion.",
        execution=[{"name": "open_application:Notion", "success": True}],
    )

    task = memory_db.get_task("task-1")
    assert task is not None
    assert task["status"] == "completed"
    assert task["prompt"] == "Open Notion"
    assert "Notion" in (task["result_text"] or "")
    assert '"success":true' in (task["execution_json"] or "")


def test_chat_history_persists_and_restores_order(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(memory_db, "DB_PATH", tmp_path / "ultron_memory.db")
    memory_db.init_memory_db()

    memory_db.log_chat("user", "Open Chrome")
    memory_db.log_chat("assistant", "Opened and verified: Chrome.")

    assert memory_db.get_recent_chat_history(10) == [
        {"role": "user", "content": "Open Chrome"},
        {"role": "assistant", "content": "Opened and verified: Chrome."},
    ]


def test_latest_task_is_most_recently_updated(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(memory_db, "DB_PATH", tmp_path / "ultron_memory.db")
    memory_db.init_memory_db()

    memory_db.create_task("task-1", "Open Notion")
    memory_db.create_task("task-2", "Open Chrome")
    memory_db.update_task("task-2", "completed", result_text="Done")

    latest = memory_db.get_latest_task()
    assert latest is not None
    assert latest["task_id"] == "task-2"
