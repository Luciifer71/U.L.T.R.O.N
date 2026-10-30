"""Lightweight structured audit logging for the ULTRON control plane."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from .models import AuditRecord


class AuditLogger:
    """Append-only JSONL audit logger.

    JSONL (one JSON object per line) is intentionally simple and easy to
    inspect, rotate, ingest into another system, or migrate into a database
    later.
    """

    def __init__(self, path: str | os.PathLike[str] = "runtime/audit/control.jsonl") -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def record(self, record: AuditRecord) -> None:
        payload: dict[str, Any] = {
            "taskId": record.task_id,
            "capability": record.capability,
            "operation": record.operation,
            "target": record.target,
            "success": record.success,
            "timestampMs": record.timestamp_ms,
            "durationMs": record.duration_ms,
            "error": record.error,
            "metadata": dict(record.metadata),
        }

        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

        with self._lock:
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")

    @staticmethod
    def now_ms() -> int:
        return int(time.time() * 1000)
