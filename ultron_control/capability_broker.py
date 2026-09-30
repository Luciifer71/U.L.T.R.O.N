"""Central capability broker for ULTRON computer control."""

from __future__ import annotations

import time
import uuid
from typing import Any

from .application_discovery import ApplicationDiscovery
from .audit import AuditLogger
from .execution import ExecutionEngine
from .filesystem import FilesystemCapability
from .models import AuditRecord, CapabilityResult
from .policy import CapabilityPolicy
from .process_control import ProcessCapability
from .terminal import TerminalCapability
from .verification import VerificationCapability


class CapabilityBroker:
    """Single entry point for ULTRON's computer-control capabilities.

    The broker is async-first. Blocking operating-system work is delegated to
    ``ExecutionEngine`` so callers can safely use the broker from ULTRON's
    asynchronous Brain without freezing its event loop.
    """

    def __init__(
        self,
        *,
        policy: CapabilityPolicy | None = None,
        audit: AuditLogger | None = None,
    ) -> None:
        self.policy = policy or CapabilityPolicy()
        self.audit = audit or AuditLogger()
        self.execution = ExecutionEngine()
        self.apps = ApplicationDiscovery()
        self.filesystem = FilesystemCapability()
        self.processes = ProcessCapability()
        self.terminal = TerminalCapability()
        self.verification = VerificationCapability()

    @staticmethod
    def _task_id(task_id: str | None) -> str:
        return task_id.strip() if task_id and task_id.strip() else str(uuid.uuid4())

    def _audit(
        self,
        *,
        task_id: str,
        capability: str,
        operation: str,
        target: str | None,
        success: bool,
        started_ms: int,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        completed_ms = int(time.time() * 1000)
        self.audit.record(
            AuditRecord(
                task_id=task_id,
                capability=capability,
                operation=operation,
                target=target,
                success=success,
                timestamp_ms=completed_ms,
                duration_ms=completed_ms - started_ms,
                error=error,
                metadata=metadata or {},
            )
        )

    async def open_application(
        self,
        app_name: str,
        *,
        task_id: str | None = None,
        verify: bool = True,
    ) -> CapabilityResult:
        """Resolve, launch, and verify a Windows application."""

        task_id = self._task_id(task_id)
        started_ms = int(time.time() * 1000)

        decision = self.policy.decide("application.open")
        if not decision.allowed:
            return CapabilityResult(
                False,
                "application.open",
                decision.reason,
                requires_confirmation=decision.requires_confirmation,
                error=decision.reason,
            )

        try:
            # Discovery performs deterministic resolution before any process is
            # launched. The discovery operation itself is blocking because it
            # may inspect PATH, registry, or Start Menu data.
            discovery_result = await self.execution.call(
                "application.resolve",
                lambda: self.apps.resolve(app_name),
            )

            if not discovery_result.success:
                error = discovery_result.error or discovery_result.message
                self._audit(
                    task_id=task_id,
                    capability="application.open",
                    operation="resolve_application",
                    target=app_name,
                    success=False,
                    started_ms=started_ms,
                    error=error,
                )
                return CapabilityResult(
                    False,
                    "application.open",
                    f"Could not resolve '{app_name}'.",
                    error=error,
                )

            resolved = discovery_result.data.get("result")
            if resolved is None:
                raise RuntimeError("Application resolver returned no resolution object.")

            launch_result = await self.execution.call(
                "application.launch",
                lambda: self.processes.launch(resolved.command),
            )

            if not launch_result.success:
                error = launch_result.error or launch_result.message
                self._audit(
                    task_id=task_id,
                    capability="application.open",
                    operation="launch_application",
                    target=app_name,
                    success=False,
                    started_ms=started_ms,
                    error=error,
                    metadata={"resolutionSource": resolved.source},
                )
                return CapabilityResult(
                    False,
                    "application.open",
                    f"Could not launch '{resolved.display_name}'.",
                    data={
                        "requested": app_name,
                        "resolved": resolved.display_name,
                        "command": list(resolved.command),
                        "source": resolved.source,
                    },
                    error=error,
                )

            launch_data = launch_result.data.get("result", {})
            pid = launch_data.get("pid") if isinstance(launch_data, dict) else None

            verification: dict[str, object] | None = None
            if verify:
                if resolved.executable:
                    verification_result = await self.execution.call(
                        "application.verify-executable",
                        lambda: self.verification.verify_executable_running(
                            resolved.executable or ""
                        ),
                    )
                elif pid is not None:
                    verification_result = await self.execution.call(
                        "application.verify-pid",
                        lambda: self.verification.verify_process_pid(int(pid)),
                    )
                else:
                    verification = {"running": False, "reason": "No verification target available."}
                    verification_result = None

                if verification_result is not None:
                    verification = (
                        verification_result.data.get("result")
                        if verification_result.success
                        else {"running": False, "error": verification_result.error}
                    )

            verified = verification is None or bool(verification.get("running"))
            if not verified:
                error = (
                    "Launch process returned but verification did not observe "
                    "the target application."
                )
                self._audit(
                    task_id=task_id,
                    capability="application.open",
                    operation="verify_application",
                    target=app_name,
                    success=False,
                    started_ms=started_ms,
                    error=error,
                    metadata={
                        "resolutionSource": resolved.source,
                        "verification": verification or {},
                    },
                )
                return CapabilityResult(
                    success=False,
                    capability="application.open",
                    message=(
                        f"{resolved.display_name} was launched but "
                        "could not be verified as running."
                    ),
                    data={
                        "requested": app_name,
                        "resolved": resolved.display_name,
                        "command": list(resolved.command),
                        "source": resolved.source,
                        "pid": pid,
                        "verification": verification or {},
                    },
                    error="Post-launch verification failed.",
                )

            self._audit(
                task_id=task_id,
                capability="application.open",
                operation="open_application",
                target=app_name,
                success=True,
                started_ms=started_ms,
                metadata={
                    "resolvedName": resolved.display_name,
                    "source": resolved.source,
                    "pid": pid,
                    "verification": verification or {},
                },
            )

            return CapabilityResult(
                success=True,
                capability="application.open",
                message=f"{resolved.display_name} opened successfully.",
                data={
                    "requested": app_name,
                    "resolved": resolved.display_name,
                    "pid": pid,
                    "command": list(resolved.command),
                    "source": resolved.source,
                    "verification": verification or {},
                },
            )

        except Exception as exc:
            self._audit(
                task_id=task_id,
                capability="application.open",
                operation="open_application",
                target=app_name,
                success=False,
                started_ms=started_ms,
                error=str(exc),
            )
            return CapabilityResult(
                success=False,
                capability="application.open",
                message=f"Could not open '{app_name}'.",
                error=str(exc),
            )

    async def list_directory(
        self,
        path: str,
        *,
        task_id: str | None = None,
    ) -> CapabilityResult:
        task_id = self._task_id(task_id)
        started_ms = int(time.time() * 1000)
        result = await self.execution.call(
            "filesystem.list",
            lambda: self.filesystem.list_directory(path),
        )
        if not result.success:
            self._audit(
                task_id=task_id,
                capability="filesystem.list",
                operation="list_directory",
                target=path,
                success=False,
                started_ms=started_ms,
                error=result.error,
            )
            return CapabilityResult(
                False,
                "filesystem.list",
                f"Could not list '{path}'.",
                error=result.error,
            )

        entries = result.data.get("result", [])
        self._audit(
            task_id=task_id,
            capability="filesystem.list",
            operation="list_directory",
            target=path,
            success=True,
            started_ms=started_ms,
            metadata={"count": len(entries) if isinstance(entries, list) else 0},
        )
        return CapabilityResult(
            True,
            "filesystem.list",
            f"Listed {len(entries)} entries." if isinstance(entries, list) else "Directory listed.",
            data={"path": str(self.filesystem.resolve(path)), "entries": entries},
        )

    async def search_files(
        self,
        root: str,
        pattern: str,
        *,
        max_results: int = 200,
        task_id: str | None = None,
    ) -> CapabilityResult:
        task_id = self._task_id(task_id)
        started_ms = int(time.time() * 1000)
        result = await self.execution.call(
            "filesystem.search",
            lambda: self.filesystem.search(root, pattern, max_results=max_results),
        )
        if not result.success:
            self._audit(
                task_id=task_id,
                capability="filesystem.search",
                operation="search_files",
                target=root,
                success=False,
                started_ms=started_ms,
                error=result.error,
            )
            return CapabilityResult(
                False,
                "filesystem.search",
                f"Search failed in '{root}'.",
                error=result.error,
            )

        results = result.data.get("result", [])
        count = len(results) if isinstance(results, list) else 0
        self._audit(
            task_id=task_id,
            capability="filesystem.search",
            operation="search_files",
            target=root,
            success=True,
            started_ms=started_ms,
            metadata={"pattern": pattern, "count": count},
        )
        return CapabilityResult(
            True,
            "filesystem.search",
            f"Found {count} matching files.",
            data={"results": results, "pattern": pattern, "root": root},
        )

    async def read_file(
        self,
        path: str,
        *,
        task_id: str | None = None,
    ) -> CapabilityResult:
        task_id = self._task_id(task_id)
        started_ms = int(time.time() * 1000)
        result = await self.execution.call(
            "filesystem.read",
            lambda: self.filesystem.read_text(path),
        )
        if not result.success:
            self._audit(
                task_id=task_id,
                capability="filesystem.read",
                operation="read_file",
                target=path,
                success=False,
                started_ms=started_ms,
                error=result.error,
            )
            return CapabilityResult(False, "filesystem.read", f"Could not read '{path}'.", error=result.error)

        content = result.data.get("result", "")
        self._audit(
            task_id=task_id,
            capability="filesystem.read",
            operation="read_file",
            target=path,
            success=True,
            started_ms=started_ms,
        )
        return CapabilityResult(
            True,
            "filesystem.read",
            f"Read '{path}'.",
            data={"path": path, "content": content},
        )

    async def write_file(
        self,
        path: str,
        content: str,
        *,
        task_id: str | None = None,
    ) -> CapabilityResult:
        task_id = self._task_id(task_id)
        decision = self.policy.decide("filesystem.write")
        if not decision.allowed:
            return CapabilityResult(
                False,
                "filesystem.write",
                decision.reason,
                requires_confirmation=decision.requires_confirmation,
                error=decision.reason,
            )

        started_ms = int(time.time() * 1000)
        result = await self.execution.call(
            "filesystem.write",
            lambda: self.filesystem.write_text(path, content),
        )
        if not result.success:
            self._audit(
                task_id=task_id,
                capability="filesystem.write",
                operation="write_file",
                target=path,
                success=False,
                started_ms=started_ms,
                error=result.error,
            )
            return CapabilityResult(False, "filesystem.write", f"Could not write '{path}'.", error=result.error)

        written = result.data.get("result", path)
        self._audit(
            task_id=task_id,
            capability="filesystem.write",
            operation="write_file",
            target=path,
            success=True,
            started_ms=started_ms,
        )
        return CapabilityResult(True, "filesystem.write", f"Wrote '{written}'.", data={"path": written})

    async def delete_file(
        self,
        path: str,
        *,
        task_id: str | None = None,
    ) -> CapabilityResult:
        task_id = self._task_id(task_id)
        decision = self.policy.decide("filesystem.delete", destructive=True)
        if not decision.allowed:
            return CapabilityResult(
                False,
                "filesystem.delete",
                decision.reason,
                requires_confirmation=decision.requires_confirmation,
                error=decision.reason,
            )

        started_ms = int(time.time() * 1000)
        result = await self.execution.call(
            "filesystem.delete",
            lambda: self.filesystem.delete(path),
        )
        success = result.success
        self._audit(
            task_id=task_id,
            capability="filesystem.delete",
            operation="delete_file",
            target=path,
            success=success,
            started_ms=started_ms,
            error=result.error,
        )
        if not success:
            return CapabilityResult(False, "filesystem.delete", f"Could not delete '{path}'.", error=result.error)
        return CapabilityResult(True, "filesystem.delete", f"Deleted '{path}'.")

    async def list_processes(
        self,
        *,
        task_id: str | None = None,
    ) -> CapabilityResult:
        task_id = self._task_id(task_id)
        started_ms = int(time.time() * 1000)
        result = await self.execution.call(
            "process.list",
            self.processes.list_processes,
        )
        if not result.success:
            self._audit(
                task_id=task_id,
                capability="process.list",
                operation="list_processes",
                target=None,
                success=False,
                started_ms=started_ms,
                error=result.error,
            )
            return CapabilityResult(False, "process.list", "Could not list processes.", error=result.error)

        processes = result.data.get("result", [])
        count = len(processes) if isinstance(processes, list) else 0
        self._audit(
            task_id=task_id,
            capability="process.list",
            operation="list_processes",
            target=None,
            success=True,
            started_ms=started_ms,
            metadata={"count": count},
        )
        return CapabilityResult(True, "process.list", f"Found {count} processes.", data={"processes": processes})

    async def terminate_process(
        self,
        pid: int,
        *,
        force: bool = False,
        task_id: str | None = None,
    ) -> CapabilityResult:
        task_id = self._task_id(task_id)
        decision = self.policy.decide("process.terminate", destructive=True)
        if not decision.allowed:
            return CapabilityResult(
                False,
                "process.terminate",
                decision.reason,
                requires_confirmation=decision.requires_confirmation,
                error=decision.reason,
            )

        started_ms = int(time.time() * 1000)
        result = await self.execution.call(
            "process.terminate",
            lambda: self.processes.terminate_pid(pid, force=force),
        )
        self._audit(
            task_id=task_id,
            capability="process.terminate",
            operation="terminate_process",
            target=str(pid),
            success=result.success,
            started_ms=started_ms,
            error=result.error,
            metadata={"force": force},
        )
        if not result.success:
            return CapabilityResult(False, "process.terminate", f"Could not terminate process {pid}.", error=result.error)
        return CapabilityResult(True, "process.terminate", f"Process {pid} termination requested.")

    async def run_terminal(
        self,
        command: str,
        *,
        cwd: str | None = None,
        timeout: float = 60.0,
        task_id: str | None = None,
    ) -> CapabilityResult:
        task_id = self._task_id(task_id)
        decision = self.policy.decide("terminal.execute")
        if not decision.allowed:
            return CapabilityResult(
                False,
                "terminal.execute",
                decision.reason,
                requires_confirmation=decision.requires_confirmation,
                error=decision.reason,
            )

        started_ms = int(time.time() * 1000)
        result = await self.execution.call(
            "terminal.execute",
            lambda: self.terminal.execute(command, cwd=cwd, timeout=timeout),
        )
        if not result.success:
            self._audit(
                task_id=task_id,
                capability="terminal.execute",
                operation="run_terminal",
                target=command,
                success=False,
                started_ms=started_ms,
                error=result.error,
            )
            return CapabilityResult(False, "terminal.execute", "Terminal execution failed.", error=result.error)

        terminal_result = result.data.get("result")
        return_code = getattr(terminal_result, "return_code", None)
        stdout = getattr(terminal_result, "stdout", "")
        stderr = getattr(terminal_result, "stderr", "")
        success = return_code == 0

        self._audit(
            task_id=task_id,
            capability="terminal.execute",
            operation="run_terminal",
            target=command,
            success=success,
            started_ms=started_ms,
            error=stderr if not success else None,
            metadata={"returnCode": return_code},
        )

        return CapabilityResult(
            success,
            "terminal.execute",
            "Terminal command completed." if success else "Terminal command failed.",
            data={
                "returnCode": return_code,
                "stdout": stdout,
                "stderr": stderr,
            },
            error=None if success else stderr,
        )
