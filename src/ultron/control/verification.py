"""Post-action verification helpers."""

from __future__ import annotations

import os
import time
from typing import Any

import psutil


class VerificationCapability:
    """Verify that requested physical actions produced expected effects."""

    @staticmethod
    def verify_process_pid(
        pid: int,
        *,
        timeout: float = 3.0,
    ) -> dict[str, object]:
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if not psutil.pid_exists(pid):
                time.sleep(0.05)
                continue

            try:
                proc = psutil.Process(pid)

                running = proc.is_running()

                if not running:
                    time.sleep(0.05)
                    continue

                try:
                    exe = proc.exe()
                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                    psutil.ZombieProcess,
                ):
                    exe = None

                try:
                    name = proc.name()
                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                    psutil.ZombieProcess,
                ):
                    name = None

                return {
                    "running": True,
                    "pid": pid,
                    "name": name,
                    "exe": exe,
                    "method": "pid",
                }

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
                psutil.ZombieProcess,
            ):
                time.sleep(0.05)

        return {
            "running": False,
            "pid": pid,
            "method": "pid",
        }

    @staticmethod
    def verify_process_identity(
        pid: int,
        expected_executable: str,
        *,
        timeout: float = 3.0,
    ) -> dict[str, object]:
        expected = os.path.basename(
            expected_executable
        ).lower()

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if not psutil.pid_exists(pid):
                time.sleep(0.05)
                continue

            try:
                proc = psutil.Process(pid)

                if not proc.is_running():
                    time.sleep(0.05)
                    continue

                try:
                    actual_exe = proc.exe()
                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                    psutil.ZombieProcess,
                ):
                    actual_exe = None

                try:
                    actual_name = proc.name()
                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                    psutil.ZombieProcess,
                ):
                    actual_name = None

                actual_basename = os.path.basename(
                    str(actual_exe or "")
                ).lower()

                process_name = str(
                    actual_name or ""
                ).lower()

                if (
                    actual_basename == expected
                    or process_name == expected
                ):
                    return {
                        "running": True,
                        "pid": pid,
                        "name": actual_name,
                        "exe": actual_exe,
                        "expectedExecutable": expected,
                        "identityMatched": True,
                        "method": "pid+identity",
                    }

                return {
                    "running": False,
                    "pid": pid,
                    "name": actual_name,
                    "exe": actual_exe,
                    "expectedExecutable": expected,
                    "identityMatched": False,
                    "method": "pid+identity",
                }

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
                psutil.ZombieProcess,
            ):
                time.sleep(0.05)

        return {
            "running": False,
            "pid": pid,
            "expectedExecutable": expected,
            "identityMatched": False,
            "method": "pid+identity",
        }

    @staticmethod
    def verify_executable_running(
        executable: str,
        *,
        timeout: float = 3.0,
    ) -> dict[str, object]:
        """
        Best-effort executable presence verification.

        This is intentionally weaker than PID verification and should only be
        used for operations where Windows may reuse an already-running shell
        process, such as Explorer.
        """

        expected = os.path.basename(
            executable
        ).lower()

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            for proc in psutil.process_iter(
                ["pid", "name", "exe"]
            ):
                try:
                    info = proc.info
                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                ):
                    continue

                names = {
                    str(info.get("name") or "").lower(),
                    os.path.basename(
                        str(info.get("exe") or "")
                    ).lower(),
                }

                if expected in names:
                    return {
                        "running": True,
                        "pid": info.get("pid"),
                        "name": info.get("name"),
                        "exe": info.get("exe"),
                        "expectedExecutable": expected,
                        "method": "executable-presence",
                        "strongVerification": False,
                    }

            time.sleep(0.05)

        return {
            "running": False,
            "expectedExecutable": expected,
            "method": "executable-presence",
            "strongVerification": False,
        }

    @staticmethod
    def verify_file_exists(path: str) -> bool:
        return os.path.isfile(
            os.path.expandvars(
                os.path.expanduser(path)
            )
        )