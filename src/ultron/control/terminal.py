"""Structured terminal capability."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from .models import CapabilityError


@dataclass(frozen=True, slots=True)
class TerminalResult:
    """Terminal execution result."""

    return_code: int
    stdout: str
    stderr: str


class TerminalCapability:
    """Execute an explicit command through a selected Windows shell."""

    def __init__(self, *, default_shell: str = "powershell") -> None:
        self.default_shell = default_shell

    def execute(
        self,
        command: str,
        *,
        shell_name: str | None = None,
        cwd: str | None = None,
        timeout: float = 60.0,
    ) -> TerminalResult:
        command = str(command).strip()
        if not command:
            raise CapabilityError("Terminal command cannot be empty.")
        if timeout <= 0:
            raise CapabilityError("Terminal timeout must be positive.")

        selected = shell_name or self.default_shell
        if os.name == "nt":
            if selected.lower() in {"powershell", "pwsh", "powershell.exe"}:
                executable = "powershell.exe" if selected.lower().startswith("powershell") else "pwsh.exe"
                argv = [
                    executable,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    command,
                ]
            elif selected.lower() in {"cmd", "cmd.exe"}:
                argv = ["cmd.exe", "/d", "/s", "/c", command]
            else:
                raise CapabilityError(f"Unsupported Windows shell: {selected}")
        else:
            raise CapabilityError("TerminalCapability is currently Windows-focused.")

        try:
            result = subprocess.run(
                argv,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CapabilityError(
                f"Terminal command exceeded the {timeout:.1f}s timeout."
            ) from exc
        except OSError as exc:
            raise CapabilityError(f"Terminal execution failed: {exc}") from exc

        return TerminalResult(
            return_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
