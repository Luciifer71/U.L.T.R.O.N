from __future__ import annotations

import ctypes

import pytest

from ultron_control.models import CapabilityError, ResolvedResource
from ultron_control.resource_execution import (
    ResourceExecutionCapability,
    SHELLEXECUTEINFOW,
    shell32,
)


def make_resource(
    *,
    kind: str,
    target: str,
    path: str | None = None,
    uri: str | None = None,
) -> ResolvedResource:
    """Build a deterministic resource for execution tests."""

    return ResolvedResource(
        requested=target,
        kind=kind,
        target=target,
        path=path,
        uri=uri,
        source="test",
        exists=True,
    )


def test_application_resources_are_rejected() -> None:
    executor = ResourceExecutionCapability()

    resource = make_resource(
        kind="application",
        target="Test Application",
    )

    with pytest.raises(
        CapabilityError,
        match="open_application",
    ):
        executor.open(resource)


def test_local_file_is_verified_after_dispatch(
    tmp_path,
    monkeypatch,
) -> None:
    executor = ResourceExecutionCapability()

    test_file = tmp_path / "example.txt"

    test_file.write_text(
        "ULTRON execution test",
        encoding="utf-8",
    )

    def fake_shell_execute(info_ptr) -> bool:
        info = ctypes.cast(
            info_ptr,
            ctypes.POINTER(SHELLEXECUTEINFOW),
        ).contents

        # Simulate Windows accepting the request without returning
        # a process handle.
        info.hProcess = None
        return True

    monkeypatch.setattr(
        shell32,
        "ShellExecuteExW",
        fake_shell_execute,
    )

    resource = make_resource(
        kind="file",
        target=str(test_file),
        path=str(test_file),
    )

    result = executor.open(resource)

    assert result.dispatched is True
    assert result.process_created is False
    assert result.pid is None
    assert result.state == "verified"
    assert result.verification == "target_exists"
    assert result.target == str(test_file)


def test_local_directory_is_verified_after_dispatch(
    tmp_path,
    monkeypatch,
) -> None:
    executor = ResourceExecutionCapability()

    def fake_shell_execute(info_ptr) -> bool:
        info = ctypes.cast(
            info_ptr,
            ctypes.POINTER(SHELLEXECUTEINFOW),
        ).contents

        info.hProcess = None
        return True

    monkeypatch.setattr(
        shell32,
        "ShellExecuteExW",
        fake_shell_execute,
    )

    resource = make_resource(
        kind="directory",
        target=str(tmp_path),
        path=str(tmp_path),
    )

    result = executor.open(resource)

    assert result.dispatched is True
    assert result.process_created is False
    assert result.pid is None
    assert result.state == "verified"
    assert result.verification == "target_exists"


def test_url_remains_dispatched_even_when_shell_accepts_it(
    monkeypatch,
) -> None:
    executor = ResourceExecutionCapability()

    def fake_shell_execute(info_ptr) -> bool:
        info = ctypes.cast(
            info_ptr,
            ctypes.POINTER(SHELLEXECUTEINFOW),
        ).contents

        info.hProcess = None
        return True

    monkeypatch.setattr(
        shell32,
        "ShellExecuteExW",
        fake_shell_execute,
    )

    resource = make_resource(
        kind="url",
        target="https://github.com",
        uri="https://github.com",
    )

    result = executor.open(resource)

    assert result.dispatched is True
    assert result.process_created is False
    assert result.pid is None
    assert result.state == "dispatched"
    assert result.verification == "not_observable"
    assert result.verification_reason is not None


def test_uri_remains_dispatched_even_when_process_is_created(
    monkeypatch,
) -> None:
    executor = ResourceExecutionCapability()

    import ultron_control.resource_execution as resource_execution

    def fake_shell_execute(info_ptr) -> bool:
        info = ctypes.cast(
            info_ptr,
            ctypes.POINTER(SHELLEXECUTEINFOW),
        ).contents

        # Simulate ShellExecuteExW returning a process handle.
        info.hProcess = ctypes.c_void_p(1)
        return True

    def fake_get_process_id(handle) -> int:
        return 12345

    def fake_close_handle(handle) -> bool:
        return True

    monkeypatch.setattr(
        shell32,
        "ShellExecuteExW",
        fake_shell_execute,
    )

    monkeypatch.setattr(
        resource_execution.kernel32,
        "GetProcessId",
        fake_get_process_id,
    )

    monkeypatch.setattr(
        resource_execution.kernel32,
        "CloseHandle",
        fake_close_handle,
    )

    resource = make_resource(
        kind="uri",
        target="steam://open/main",
        uri="steam://open/main",
    )

    result = executor.open(resource)

    assert result.dispatched is True
    assert result.process_created is True
    assert result.pid == 12345

    # A process existing does NOT prove that the requested URI
    # action completed.
    assert result.state == "dispatched"
    assert result.verification == "not_observable"
    assert result.verification_reason is not None


def test_missing_target_is_rejected() -> None:
    executor = ResourceExecutionCapability()

    resource = ResolvedResource(
        requested="broken-resource",
        kind="file",
        target="broken-resource",
        path=None,
        uri=None,
        source="test",
        exists=False,
    )

    with pytest.raises(
        CapabilityError,
        match="has no executable target",
    ):
        executor.open(resource)