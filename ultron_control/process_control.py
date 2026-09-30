"""Windows process capabilities."""

from __future__ import annotations

import ctypes
import os
import subprocess
import uuid
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

import psutil

from .models import CapabilityError, ResolvedApplication


# ---------------------------------------------------------------------------
# Native Windows COM definitions
# ---------------------------------------------------------------------------

class _GUID(ctypes.Structure):
    """Windows GUID structure used by COM."""

    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        (
            "Data4",
            ctypes.c_ubyte * 8,
        ),
    ]


def _guid(value: str) -> _GUID:
    """Convert a UUID string into a Windows GUID structure."""

    parsed = uuid.UUID(value)
    raw = parsed.bytes_le

    result = _GUID()

    ctypes.memmove(
        ctypes.byref(result),
        raw,
        ctypes.sizeof(result),
    )

    return result


# CLSID_ApplicationActivationManager
_CLSID_APPLICATION_ACTIVATION_MANAGER = _guid(
    "45BA127D-10A8-46EA-8AB7-56EA9078943C"
)

# IID_IApplicationActivationManager
_IID_IAPPLICATION_ACTIVATION_MANAGER = _guid(
    "2E941141-7F97-4756-BA1D-9DECDE894A3D"
)


# ---------------------------------------------------------------------------
# COM constants
# ---------------------------------------------------------------------------

_CLSCTX_LOCAL_SERVER = 0x4

_COINIT_APARTMENTTHREADED = 0x2

_S_OK = 0
_S_FALSE = 1

_AO_NONE = 0


# ---------------------------------------------------------------------------
# Launch result
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class LaunchResult:
    """Normalized physical launch result."""

    pid: int
    method: str
    process: subprocess.Popen[bytes] | None = None


# ---------------------------------------------------------------------------
# Process capability
# ---------------------------------------------------------------------------

class ProcessCapability:
    """Inspect and control processes through structured operations."""

    @staticmethod
    def list_processes() -> list[dict[str, Any]]:
        """Return information about currently running processes."""

        processes: list[dict[str, Any]] = []

        for proc in psutil.process_iter(
            [
                "pid",
                "name",
                "exe",
                "username",
            ]
        ):
            try:
                info = proc.info
            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
            ):
                continue

            processes.append(info)

        return processes

    @staticmethod
    def find(
        name: str,
    ) -> list[dict[str, Any]]:
        """Find running processes by executable name."""

        normalized = (
            str(name)
            .lower()
            .removesuffix(".exe")
        )

        return [
            item
            for item in ProcessCapability.list_processes()
            if (
                str(
                    item.get("name") or ""
                )
                .lower()
                .removesuffix(".exe")
                == normalized
            )
        ]

    @staticmethod
    def terminate_pid(
        pid: int,
        *,
        force: bool = False,
    ) -> None:
        """Terminate a process by PID."""

        try:
            proc = psutil.Process(pid)
        except psutil.NoSuchProcess as exc:
            raise CapabilityError(
                f"Process {pid} does not exist."
            ) from exc

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
        """Launch an executable without invoking a shell."""

        if (
            not command
            or not all(
                isinstance(part, str)
                and part
                for part in command
            )
        ):
            raise CapabilityError(
                "Launch command must be a non-empty argument list."
            )

        return subprocess.Popen(
            list(command),
            cwd=cwd,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(
                subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0,
            ),
        )

    # ------------------------------------------------------------------
    # Application launcher
    # ------------------------------------------------------------------

    @classmethod
    def launch_application(
        cls,
        application: ResolvedApplication,
    ) -> LaunchResult:
        """
        Launch a resolved application using the appropriate mechanism.

        windows-appx:
            Native Windows AUMID activation.

        Everything else:
            Validated executable/AppFolder command through shell=False.
        """

        # --------------------------------------------------------------
        # Genuine AppX/MSIX application
        # --------------------------------------------------------------
        if (
            application.source == "windows-appx"
            and application.app_id
        ):
            pid = cls.activate_application(
                application.app_id
            )

            if pid <= 0:
                raise CapabilityError(
                    f"Windows activated "
                    f"'{application.display_name}' "
                    "but returned no usable process ID."
                )

            return LaunchResult(
                pid=pid,
                method="windows-app-activation",
                process=None,
            )

        # --------------------------------------------------------------
        # Normal executable OR Start Menu fallback
        # --------------------------------------------------------------
        process = cls.launch(
            application.command
        )

        if process.pid <= 0:
            raise CapabilityError(
                f"Launch of '{application.display_name}' "
                "returned an invalid process ID."
            )

        method = (
            "start-menu-shell"
            if application.source
            == "windows-start-menu"
            else "direct-executable"
        )

        return LaunchResult(
            pid=process.pid,
            method=method,
            process=process,
        )

    # ------------------------------------------------------------------
    # Native Windows AppX/MSIX activation
    # ------------------------------------------------------------------

    @staticmethod
    def activate_application(
        app_user_model_id: str,
        *,
        arguments: str = "",
    ) -> int:
        """
        Activate a Windows packaged application by canonical AUMID.

        The canonical packaged AUMID has the form:

            PackageFamilyName!ApplicationId

        IApplicationActivationManager::ActivateApplication returns
        the process ID of the activated application instance.
        """

        if os.name != "nt":
            raise CapabilityError(
                "Windows application activation is only "
                "available on Windows."
            )

        app_user_model_id = str(
            app_user_model_id or ""
        ).strip()

        if not app_user_model_id:
            raise CapabilityError(
                "AUMID must be a non-empty string."
            )

        arguments = str(
            arguments or ""
        )

        # --------------------------------------------------------------
        # Load COM runtime
        # --------------------------------------------------------------
        ole32 = ctypes.WinDLL(
            "ole32.dll"
        )

        # --------------------------------------------------------------
        # CoInitializeEx
        # --------------------------------------------------------------
        co_initialize_ex = (
            ole32.CoInitializeEx
        )

        co_initialize_ex.argtypes = [
            wintypes.LPVOID,
            wintypes.DWORD,
        ]

        co_initialize_ex.restype = ctypes.c_long

        # --------------------------------------------------------------
        # CoUninitialize
        # --------------------------------------------------------------
        co_uninitialize = (
            ole32.CoUninitialize
        )

        co_uninitialize.argtypes = []
        co_uninitialize.restype = None

        # --------------------------------------------------------------
        # CoCreateInstance
        # --------------------------------------------------------------
        co_create_instance = (
            ole32.CoCreateInstance
        )

        co_create_instance.argtypes = [
            ctypes.POINTER(_GUID),
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(_GUID),
            ctypes.POINTER(
                ctypes.c_void_p
            ),
        ]

        co_create_instance.restype = ctypes.c_long

        # --------------------------------------------------------------
        # Initialize COM for this worker thread
        # --------------------------------------------------------------
        hr = co_initialize_ex(
            None,
            _COINIT_APARTMENTTHREADED,
        )

        if hr not in (
            _S_OK,
            _S_FALSE,
        ):
            raise CapabilityError(
                "CoInitializeEx failed with HRESULT "
                f"0x{hr & 0xFFFFFFFF:08X}."
            )

        manager = ctypes.c_void_p()

        try:
            # ----------------------------------------------------------
            # Create IApplicationActivationManager
            # ----------------------------------------------------------
            hr = co_create_instance(
                ctypes.byref(
                    _CLSID_APPLICATION_ACTIVATION_MANAGER
                ),
                None,
                _CLSCTX_LOCAL_SERVER,
                ctypes.byref(
                    _IID_IAPPLICATION_ACTIVATION_MANAGER
                ),
                ctypes.byref(
                    manager
                ),
            )

            if (
                hr != _S_OK
                or not manager.value
            ):
                raise CapabilityError(
                    "Could not create "
                    "IApplicationActivationManager "
                    f"(HRESULT "
                    f"0x{hr & 0xFFFFFFFF:08X})."
                )

            # ----------------------------------------------------------
            # Interface vtable
            #
            # IUnknown:
            #   0 = QueryInterface
            #   1 = AddRef
            #   2 = Release
            #
            # IApplicationActivationManager:
            #   3 = ActivateApplication
            # ----------------------------------------------------------
            vtable = ctypes.cast(
                manager,
                ctypes.POINTER(
                    ctypes.POINTER(
                        ctypes.c_void_p
                    )
                ),
            ).contents

            # HRESULT ActivateApplication(
            #     LPCWSTR appUserModelId,
            #     LPCWSTR arguments,
            #     ACTIVATEOPTIONS options,
            #     DWORD* processId
            # );
            activate_application = (
                ctypes.WINFUNCTYPE(
                    ctypes.c_long,
                    ctypes.c_void_p,
                    wintypes.LPCWSTR,
                    wintypes.LPCWSTR,
                    wintypes.DWORD,
                    ctypes.POINTER(
                        wintypes.DWORD
                    ),
                )(vtable[3])
            )

            process_id = wintypes.DWORD(
                0
            )

            # ----------------------------------------------------------
            # Native packaged-app activation
            # ----------------------------------------------------------
            hr = activate_application(
                manager,
                app_user_model_id,
                arguments,
                _AO_NONE,
                ctypes.byref(
                    process_id
                ),
            )

            if hr != _S_OK:
                raise CapabilityError(
                    "ActivateApplication failed for "
                    f"'{app_user_model_id}' "
                    f"(HRESULT "
                    f"0x{hr & 0xFFFFFFFF:08X})."
                )

            pid = int(
                process_id.value
            )

            if pid <= 0:
                raise CapabilityError(
                    "ActivateApplication succeeded but "
                    "returned an invalid process ID."
                )

            return pid

        finally:
            # ----------------------------------------------------------
            # Release COM interface
            # ----------------------------------------------------------
            if manager.value:
                vtable = ctypes.cast(
                    manager,
                    ctypes.POINTER(
                        ctypes.POINTER(
                            ctypes.c_void_p
                        )
                    ),
                ).contents

                release = (
                    ctypes.WINFUNCTYPE(
                        wintypes.ULONG,
                        ctypes.c_void_p,
                    )(vtable[2])
                )

                release(
                    manager
                )

            # ----------------------------------------------------------
            # Uninitialize COM
            # ----------------------------------------------------------
            co_uninitialize()