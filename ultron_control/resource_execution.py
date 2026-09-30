"""Windows Shell execution for universal ULTRON resources."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import Literal

from .models import CapabilityError, ResolvedResource


shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


SEE_MASK_NOCLOSEPROCESS = 0x00000040
SEE_MASK_NOASYNC = 0x00000100
SW_SHOWNORMAL = 1


ExecutionState = Literal[
    "dispatched",
    "launched",
    "verified",
]

VerificationState = Literal[
    "not_requested",
    "not_observable",
    "target_exists",
]


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", wintypes.LPVOID),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIcon", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


shell32.ShellExecuteExW.argtypes = [
    ctypes.POINTER(SHELLEXECUTEINFOW),
]
shell32.ShellExecuteExW.restype = wintypes.BOOL

kernel32.GetProcessId.argtypes = [
    wintypes.HANDLE,
]
kernel32.GetProcessId.restype = wintypes.DWORD

kernel32.CloseHandle.argtypes = [
    wintypes.HANDLE,
]
kernel32.CloseHandle.restype = wintypes.BOOL


@dataclass(frozen=True, slots=True)
class ShellLaunchResult:
    """Detailed outcome of a Windows Shell launch."""

    target: str
    kind: str

    # Windows accepted the shell request.
    dispatched: bool

    # A process handle was returned by ShellExecuteExW.
    process_created: bool

    pid: int | None

    # Highest trustworthy execution state.
    state: ExecutionState

    # Whether the requested resource itself could be verified.
    verification: VerificationState

    verification_reason: str | None = None


class ResourceExecutionCapability:
    """Execute resolved resources through the Windows Shell."""

    def open(self, resource: ResolvedResource) -> ShellLaunchResult:
        if resource.kind == "application":
            raise CapabilityError(
                "Application resources must be launched through "
                "CapabilityBroker.open_application()."
            )

        target = (
            resource.uri
            if resource.kind in {"url", "uri"}
            else resource.path
        )

        if not target:
            raise CapabilityError(
                f"Resolved resource '{resource.requested}' "
                "has no executable target."
            )

        info = SHELLEXECUTEINFOW()
        info.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
        info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
        info.hwnd = None
        info.lpVerb = "open"
        info.lpFile = target
        info.lpParameters = None
        info.lpDirectory = None
        info.nShow = SW_SHOWNORMAL
        info.hInstApp = None
        info.lpIDList = None
        info.lpClass = None
        info.hkeyClass = None
        info.dwHotKey = 0
        info.hIcon = None
        info.hProcess = None

        success = bool(
            shell32.ShellExecuteExW(
                ctypes.byref(info)
            )
        )

        if not success:
            error_code = ctypes.get_last_error()
            raise ctypes.WinError(error_code)

        pid: int | None = None

        if info.hProcess:
            try:
                raw_pid = kernel32.GetProcessId(
                    info.hProcess
                )

                if raw_pid:
                    pid = int(raw_pid)
            finally:
                kernel32.CloseHandle(info.hProcess)

        process_created = pid is not None

        # ---------------------------------------------------------
        # Local resources
        # ---------------------------------------------------------
        #
        # We can verify that the requested resource still exists,
        # but we cannot prove that a GUI window became visible.
        # ---------------------------------------------------------

        if resource.kind in {
            "file",
            "directory",
            "drive",
        }:
            verification = "target_exists"

            if resource.path and self._target_exists(resource.path):
                state: ExecutionState = "verified"
                verification_reason = (
                    "Windows accepted the open request and "
                    "the target resource exists."
                )
            elif process_created:
                state = "launched"
                verification_reason = (
                    "Windows accepted the open request and "
                    "returned a process handle, but the target "
                    "resource could not be re-verified."
                )
            else:
                state = "dispatched"
                verification_reason = (
                    "Windows accepted the open request, but "
                    "post-open verification was inconclusive."
                )

            return ShellLaunchResult(
                target=target,
                kind=resource.kind,
                dispatched=True,
                process_created=process_created,
                pid=pid,
                state=state,
                verification=verification,
                verification_reason=verification_reason,
            )

        # ---------------------------------------------------------
        # URLs / URI schemes
        # ---------------------------------------------------------
        #
        # Windows can hand these to another application, an existing
        # process, DDE, or a registered protocol handler.
        #
        # A returned process does NOT prove that the intended URI
        # action was completed. Therefore URI resources remain in
        # "dispatched" state until a future protocol-specific
        # verification layer can establish the final outcome.
        # ---------------------------------------------------------

        state: ExecutionState = "dispatched"

        return ShellLaunchResult(
            target=target,
            kind=resource.kind,
            dispatched=True,
            process_created=process_created,
            pid=pid,
            state=state,
            verification="not_observable",
            verification_reason=(
                "Windows accepted the URI request, but the final "
                "protocol-handler action cannot be reliably verified "
                "from ShellExecuteExW alone."
            ),
        )

    @staticmethod
    def _target_exists(path: str) -> bool:
        try:
            return bool(
                ctypes.windll.kernel32.GetFileAttributesW(path)
                != 0xFFFFFFFF
            )
        except Exception:
            return False