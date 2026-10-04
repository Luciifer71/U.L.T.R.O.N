import json
import sqlite3
from pathlib import Path
from typing import Any

# DB file stored in local project directory
DB_PATH = Path(__file__).parent / "ultron_memory.db"


def get_db_connection() -> sqlite3.Connection:
    """Connect to SQLite and return dictionary-like rows."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_memory_db():
    """Initialize durable user, conversation, and task-memory tables."""
    with get_db_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS user_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS chat_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL,
                result_text TEXT,
                error_text TEXT,
                execution_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_updated_at
                ON tasks(updated_at DESC);

            CREATE TABLE IF NOT EXISTS task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                data_json TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(task_id) REFERENCES tasks(task_id)
            );

            CREATE INDEX IF NOT EXISTS idx_task_events_task_id
                ON task_events(task_id, id);
            """
        )
        conn.commit()
    print("[SQLITE MEMORY]: Database initialized successfully.")


# --- Fact Management Tools ---

def save_fact(key: str, value: str, category: str = "general") -> str:
    """Insert or update a key-value fact in long-term memory."""
    key = key.lower().strip()
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_facts (key, value, category, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                category = excluded.category,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, value, category),
        )
        conn.commit()
    return f"Fact stored: '{key}' = '{value}'"


def get_all_facts() -> list[dict]:
    """Retrieve all stored user facts."""
    with get_db_connection() as conn:
        cursor = conn.execute(
            "SELECT key, value, category FROM user_facts ORDER BY updated_at DESC"
        )
        return [dict(row) for row in cursor.fetchall()]


def query_facts(search_term: str) -> list[dict]:
    """Search for specific facts matching a key or value keyword."""
    term = f"%{search_term.lower().strip()}%"
    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            SELECT key, value, category FROM user_facts
            WHERE key LIKE ? OR value LIKE ? OR category LIKE ?
            ORDER BY updated_at DESC
            """,
            (term, term, term),
        )
        return [dict(row) for row in cursor.fetchall()]


# --- Chat History Persistence ---

def log_chat(role: str, content: str):
    """Save a chat message turn to persistent history."""
    if not content:
        return
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO chat_logs (role, content) VALUES (?, ?)",
            (role, content),
        )
        conn.commit()


def get_recent_chat_history(limit: int = 10) -> list[dict]:
    """Load the last N chat turns in chronological order."""
    limit = max(1, min(int(limit), 100))
    with get_db_connection() as conn:
        cursor = conn.execute(
            "SELECT role, content FROM chat_logs ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
        return [
            {"role": row["role"], "content": row["content"]}
            for row in reversed(rows)
        ]


# --- Durable Task Memory ---

def _serialize_execution(execution: list[dict[str, Any]] | None) -> str | None:
    if execution is None:
        return None
    return json.dumps(execution, separators=(",", ":"), default=str)


def create_task(task_id: str, prompt: str, status: str = "received") -> None:
    """Create one durable task record and its initial lifecycle event."""
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO tasks (task_id, prompt, status)
            VALUES (?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                prompt = excluded.prompt,
                status = excluded.status,
                updated_at = CURRENT_TIMESTAMP
            """,
            (task_id, prompt, status),
        )
        conn.execute(
            """
            INSERT INTO task_events (task_id, status, message)
            VALUES (?, ?, ?)
            """,
            (task_id, status, "Task created."),
        )
        conn.commit()


def update_task(
    task_id: str,
    status: str,
    *,
    result_text: str | None = None,
    error_text: str | None = None,
    execution: list[dict[str, Any]] | None = None,
    event_message: str | None = None,
) -> None:
    """Persist task state, result/error, execution evidence, and lifecycle event."""
    terminal = status in {"completed", "failed", "cancelled"}
    execution_json = _serialize_execution(execution)
    with get_db_connection() as conn:
        conn.execute(
            """
            UPDATE tasks
            SET status = ?,
                result_text = COALESCE(?, result_text),
                error_text = COALESCE(?, error_text),
                execution_json = COALESCE(?, execution_json),
                updated_at = CURRENT_TIMESTAMP,
                completed_at = CASE
                    WHEN ? THEN COALESCE(completed_at, CURRENT_TIMESTAMP)
                    ELSE completed_at
                END
            WHERE task_id = ?
            """,
            (
                status,
                result_text,
                error_text,
                execution_json,
                terminal,
                task_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO task_events (task_id, status, message, data_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                task_id,
                status,
                event_message or status.replace("_", " ").capitalize() + ".",
                execution_json,
            ),
        )
        conn.commit()


def get_task(task_id: str) -> dict | None:
    """Retrieve one durable task by ID."""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return dict(row) if row else None


def get_latest_task() -> dict | None:
    """Retrieve the most recently updated task."""
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM tasks
            ORDER BY datetime(updated_at) DESC, rowid DESC
            LIMIT 1
            """
        ).fetchone()
        return dict(row) if row else None


def get_recent_tasks(limit: int = 20) -> list[dict]:
    """Retrieve recent durable tasks for future task-history tools."""
    limit = max(1, min(int(limit), 100))
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM tasks
            ORDER BY datetime(updated_at) DESC, rowid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


if __name__ == "__main__":
    init_memory_db()
