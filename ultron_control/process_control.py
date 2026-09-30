"""Windows process capabilities."""

from __future__ import annotations

import os
import signal
import subprocess
from typing import Any

import psutil

from .models import CapabilityError


class ProcessCapability:
    """Inspect and control processes through structured operations."""

    @staticmethod
    def list_processes() -> list[dict[str, Any]]:
        processes: list[dict[str, Any]] = []
        for proc in psutil.process_iter(["pid", "name", "exe", "username"]):
            try:
                info = proc.info
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            processes.append(info)
        return processes

    @staticmethod
    def find(name: str) -> list[dict[str, Any]]:
        normalized = str(name).lower().removesuffix(".exe")
        return [
            item
            for item in ProcessCapability.list_processes()
            if str(item.get("name") or "").lower().removesuffix(".exe") == normalized
        ]

    @staticmethod
    def terminate_pid(pid: int, *, force: bool = False) -> None:
        try:
            proc = psutil.Process(pid)
        except psutil.NoSuchProcess as exc:
            raise CapabilityError(f"Process {pid} does not exist.") from exc

        if force:
            proc.kill()
        else:
            proc.terminate()

    @staticmethod
    def launch(
        command: list[str] | tuple[str, ...],
        *,
        cwd: str | None = None,
    ) -> subprocess.Popen[bytes]:
        if not command or not all(isinstance(part, str) and part for part in command):
            raise CapabilityError("Launch command must be a non-empty argument list.")

        return subprocess.Popen(
            list(command),
            cwd=cwd,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
