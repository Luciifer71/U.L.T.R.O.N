"""Central capability broker for ULTRON computer control."""

from __future__ import annotations

import time
import uuid
from typing import Any

from .application_discovery import ApplicationDiscovery
from .audit import AuditLogger
from .execution import ExecutionEngine
from .filesystem import FilesystemCapability
from .models import AuditRecord, CapabilityResult, PolicyDenied
from .policy import CapabilityPolicy
from .process_control import ProcessCapability
from .terminal import TerminalCapability
from .verification import VerificationCapability


class CapabilityBroker:
    """Single entry point for ULTRON's computer-control capabilities."""

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

    def _task_id(self, task_id: str | None) -> str:
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
        self.audit.record(
            AuditRecord(
                task_id=task_id,
                capability=capability,
                operation=operation,
                target=target,
                success=success,
                timestamp_ms=int(time.time() * 1000),
                duration_ms=int(time.time() * 1000) - started_ms,
                error=error,
                metadata=metadata or {},
            )
        )

    def open_application(
        self,
        app_name: str,
        *,
        task_id: str | None = None,
        verify: bool = True,
    ) -> CapabilityResult:
        task_id = self._task_id(task_id)
        started_ms = int(time.time() * 1000)

        try:
            resolved = self.apps.resolve(app_name)
            result = self.processes.launch(resolved.command)
            verification: dict[str, object] | None = None

            if verify:
                if resolved.executable:
                    verification = self.verification.verify_executable_running(
                        resolved.executable
                    )
                else:
                    verification = self.verification.verify_process_pid(result.pid)

            verified = verification is None or bool(verification.get("running"))
            if not verified:
                self._audit(
                    task_id=task_id,
                    capability="application.open",
                    operation="open_application",
                    target=app_name,
                    success=False,
                    started_ms=started_ms,
                    error="Launch process returned but verification did not observe the target application.",
                    metadata={"resolutionSource": resolved.source},
                )
                return CapabilityResult(
                    success=False,
                    capability="application.open",
                    message=f"{resolved.display_name} was launched but could not be verified as running.",
                    data={
                        "requested": app_name,
                        "resolved": resolved.display_name,
                        "command": list(resolved.command),
                        "source": resolved.source,
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
                },
            )

            return CapabilityResult(
                success=True,
                capability="application.open",
                message=f"{resolved.display_name} opened successfully.",
                data={
                    "requested": app_name,
                    "resolved": resolved.display_name,
                    "pid": result.pid,
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

    def list_directory(self, path: str, *, task_id: str | None = None) -> CapabilityResult:
        task_id = self._task_id(task_id)
        started_ms = int(time.time() * 1000)
        try:
            entries = self.filesystem.list_directory(path)
            self._audit(
                task_id=task_id,
                capability="filesystem.list",
                operation="list_directory",
                target=path,
                success=True,
                started_ms=started_ms,
            )
            return CapabilityResult(
                success=True,
                capability="filesystem.list",
                message=f"Listed {len(entries)} entries.",
                data={"path": str(self.filesystem.resolve(path)), "entries": entries},
            )
        except Exception as exc:
            self._audit(
                task_id=task_id,
                capability="filesystem.list",
                operation="list_directory",
                target=path,
                success=False,
                started_ms=started_ms,
                error=str(exc),
            )
            return CapabilityResult(False, "filesystem.list", f"Could not list '{path}'.", error=str(exc))

    def search_files(
        self,
        root: str,
        pattern: str,
        *,
        max_results: int = 200,
        task_id: str | None = None,
    ) -> CapabilityResult:
        task_id = self._task_id(task_id)
        started_ms = int(time.time() * 1000)
        try:
            results = self.filesystem.search(root, pattern, max_results=max_results)
            self._audit(
                task_id=task_id,
                capability="filesystem.search",
                operation="search_files",
                target=root,
                success=True,
                started_ms=started_ms,
                metadata={"pattern": pattern, "count": len(results)},
            )
            return CapabilityResult(
                True,
                "filesystem.search",
                f"Found {len(results)} matching files.",
                data={"results": results, "pattern": pattern, "root": root},
            )
        except Exception as exc:
            self._audit(
                task_id=task_id,
                capability="filesystem.search",
                operation="search_files",
                target=root,
                success=False,
                started_ms=started_ms,
                error=str(exc),
            )
            return CapabilityResult(False, "filesystem.search", f"Search failed in '{root}'.", error=str(exc))

    def read_file(self, path: str, *, task_id: str | None = None) -> CapabilityResult:
        task_id = self._task_id(task_id)
        started_ms = int(time.time() * 1000)
        try:
            content = self.filesystem.read_text(path)
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
        except Exception as exc:
            self._audit(
                task_id=task_id,
                capability="filesystem.read",
                operation="read_file",
                target=path,
                success=False,
                started_ms=started_ms,
                error=str(exc),
            )
            return CapabilityResult(False, "filesystem.read", f"Could not read '{path}'.", error=str(exc))

    def write_file(
        self,
        path: str,
        content: str,
        *,
        task_id: str | None = None,
    ) -> CapabilityResult:
        task_id = self._task_id(task_id)
        started_ms = int(time.time() * 1000)
        try:
            written = self.filesystem.write_text(path, content)
            self._audit(
                task_id=task_id,
                capability="filesystem.write",
                operation="write_file",
                target=path,
                success=True,
                started_ms=started_ms,
            )
            return CapabilityResult(True, "filesystem.write", f"Wrote '{written}'.", data={"path": written})
        except Exception as exc:
            self._audit(
                task_id=task_id,
                capability="filesystem.write",
                operation="write_file",
                target=path,
                success=False,
                started_ms=started_ms,
                error=str(exc),
            )
            return CapabilityResult(False, "filesystem.write", f"Could not write '{path}'.", error=str(exc))

    def delete_file(
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
        try:
            self.filesystem.delete(path)
            self._audit(
                task_id=task_id,
                capability="filesystem.delete",
                operation="delete_file",
                target=path,
                success=True,
                started_ms=started_ms,
            )
            return CapabilityResult(True, "filesystem.delete", f"Deleted '{path}'.")
        except Exception as exc:
            self._audit(
                task_id=task_id,
                capability="filesystem.delete",
                operation="delete_file",
                target=path,
                success=False,
                started_ms=started_ms,
                error=str(exc),
            )
            return CapabilityResult(False, "filesystem.delete", f"Could not delete '{path}'.", error=str(exc))

    def list_processes(self, *, task_id: str | None = None) -> CapabilityResult:
        task_id = self._task_id(task_id)
        started_ms = int(time.time() * 1000)
        try:
            processes = self.processes.list_processes()
            self._audit(
                task_id=task_id,
                capability="process.list",
                operation="list_processes",
                target=None,
                success=True,
                started_ms=started_ms,
                metadata={"count": len(processes)},
            )
            return CapabilityResult(True, "process.list", f"Found {len(processes)} processes.", data={"processes": processes})
        except Exception as exc:
            self._audit(
                task_id=task_id,
                capability="process.list",
                operation="list_processes",
                target=None,
                success=False,
                started_ms=started_ms,
                error=str(exc),
            )
            return CapabilityResult(False, "process.list", "Could not list processes.", error=str(exc))

    def terminate_process(
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
        try:
            self.processes.terminate_pid(pid, force=force)
            self._audit(
                task_id=task_id,
                capability="process.terminate",
                operation="terminate_process",
                target=str(pid),
                success=True,
                started_ms=started_ms,
                metadata={"force": force},
            )
            return CapabilityResult(True, "process.terminate", f"Process {pid} termination requested.")
        except Exception as exc:
            self._audit(
                task_id=task_id,
                capability="process.terminate",
                operation="terminate_process",
                target=str(pid),
                success=False,
                started_ms=started_ms,
                error=str(exc),
            )
            return CapabilityResult(False, "process.terminate", f"Could not terminate process {pid}.", error=str(exc))

    def run_terminal(
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
        try:
            result = self.terminal.execute(command, cwd=cwd, timeout=timeout)
            success = result.return_code == 0
            self._audit(
                task_id=task_id,
                capability="terminal.execute",
                operation="run_terminal",
                target=command,
                success=success,
                started_ms=started_ms,
                error=result.stderr if not success else None,
                metadata={"returnCode": result.return_code},
            )
            return CapabilityResult(
                success,
                "terminal.execute",
                "Terminal command completed." if success else "Terminal command failed.",
                data={
                    "returnCode": result.return_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
                error=None if success else result.stderr,
            )
        except Exception as exc:
            self._audit(
                task_id=task_id,
                capability="terminal.execute",
                operation="run_terminal",
                target=command,
                success=False,
                started_ms=started_ms,
                error=str(exc),
            )
            return CapabilityResult(False, "terminal.execute", "Terminal execution failed.", error=str(exc))
