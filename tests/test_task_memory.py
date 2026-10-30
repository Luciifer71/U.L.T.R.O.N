from __future__ import annotations

from ultron.core import memory_db
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


def test_latest_task_excludes_health_request(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_db, 'DB_PATH', tmp_path / 'memory.db')
    memory_db.init_memory_db()
    memory_db.create_task('previous', 'Open note')
    memory_db.update_task('previous', 'failed', error_text='Missing file')
    memory_db.create_task('health', 'Any problems?')
    assert memory_db.get_latest_task()['task_id'] == 'health'
    assert memory_db.get_latest_task(exclude_task_id='health')['task_id'] == 'previous'


def test_memory_connections_close_after_success_and_failure(tmp_path, monkeypatch):
    import sqlite3
    import pytest
    monkeypatch.setattr(memory_db, 'DB_PATH', tmp_path / 'memory.db')
    original = memory_db.get_db_connection
    opened = []
    def tracked():
        conn = original(); opened.append(conn); return conn
    monkeypatch.setattr(memory_db, 'get_db_connection', tracked)
    memory_db.init_memory_db()
    memory_db.save_fact('test', 'value')
    assert memory_db.get_all_facts()[0]['value'] == 'value'
    with pytest.raises(sqlite3.IntegrityError):
        memory_db.save_fact('invalid', None)
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            connection.execute('SELECT 1')
