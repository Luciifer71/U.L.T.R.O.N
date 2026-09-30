"""Execution engine used by the capability broker."""

from __future__ import annotations

import asyncio
import subprocess
import time
from collections.abc import Callable
from typing import Any

from .models import ActionResult


class ExecutionEngine:
    """Run blocking capability operations without freezing the async Brain."""

    async def call(
        self,
        operation: str,
        func: Callable[[], Any],
    ) -> ActionResult:
        started = time.time()
        started_ms = int(started * 1000)

        try:
            result = await asyncio.to_thread(func)
        except Exception as exc:
            return ActionResult(
                success=False,
                operation=operation,
                message=f"Operation failed: {exc}",
                error=str(exc),
                started_at_ms=started_ms,
                completed_at_ms=int(time.time() * 1000),
            )

        return ActionResult(
            success=True,
            operation=operation,
            message="Operation completed.",
            data={"result": self._safe_result(result)},
            started_at_ms=started_ms,
            completed_at_ms=int(time.time() * 1000),
        )

    @staticmethod
    def _safe_result(result: Any) -> Any:
        if isinstance(result, subprocess.Popen):
            return {
                "pid": result.pid,
                "poll": result.poll(),
            }
        return result
