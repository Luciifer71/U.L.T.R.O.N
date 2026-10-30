"""Execution engine for ULTRON's control plane.

The execution engine is the single async boundary between the capability broker
and blocking operating-system work. Capability modules remain synchronous and
focused on OS interactions; the engine runs those operations away from the
Brain event loop and normalizes their results.
"""

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
        """Execute one blocking operation in a worker thread.

        The callable must contain the physical operation itself. The engine
        records timing and converts the result into a stable ``ActionResult``
        contract consumed by the capability broker.
        """

        started_ms = int(time.time() * 1000)

        try:
            result = await asyncio.to_thread(func)
        except asyncio.CancelledError:
            raise
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
        """Convert non-serializable process handles into stable metadata."""

        if isinstance(result, subprocess.Popen):
            return {
                "pid": result.pid,
                "poll": result.poll(),
            }

        return result
