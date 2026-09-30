"""Post-action verification helpers."""

from __future__ import annotations

import os
import time
from collections.abc import Sequence

import psutil

from .models import CapabilityError


class VerificationCapability:
    """Verify that requested physical actions produced expected effects."""

    @staticmethod
    def verify_process_pid(pid: int, *, timeout: float = 3.0) -> dict[str, object]:
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if psutil.pid_exists(pid):
                try:
                    proc = psutil.Process(pid)
                    return {
                        "running": proc.is_running(),
                        "pid": pid,
                        "name": proc.name(),
                        "exe": proc.exe() if proc.exe() else None,
                    }
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    return {"running": True, "pid": pid}
            time.sleep(0.05)

        return {"running": False, "pid": pid}

    @staticmethod
    def verify_executable_running(
        executable: str,
        *,
        timeout: float = 3.0,
    ) -> dict[str, object]:
        expected = os.path.basename(executable).lower()
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            for proc in psutil.process_iter(["pid", "name", "exe"]):
                try:
                    info = proc.info
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

                names = {
                    str(info.get("name") or "").lower(),
                    os.path.basename(str(info.get("exe") or "")).lower(),
                }
                if expected in names:
                    return {
                        "running": True,
                        "pid": info.get("pid"),
                        "name": info.get("name"),
                        "exe": info.get("exe"),
                    }
            time.sleep(0.05)

        return {"running": False, "expectedExecutable": expected}

    @staticmethod
    def verify_file_exists(path: str) -> bool:
        return os.path.isfile(os.path.expandvars(os.path.expanduser(path)))
