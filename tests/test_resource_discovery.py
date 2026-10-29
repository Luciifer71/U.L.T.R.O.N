from __future__ import annotations

import os

import pytest

from ultron_control.application_discovery import ApplicationDiscovery
from ultron_control.models import ResolvedApplication
from ultron_control.resource_discovery import (
    ResourceDiscovery,
    ResourceNotFound,
)


class StubApplicationDiscovery(ApplicationDiscovery):
    """Deterministic application resolver for unit tests."""

    def resolve(self, name: str) -> ResolvedApplication:
        normalized = self.normalize_name(name)

        if normalized == "test application":
            return ResolvedApplication(
                requested_name=normalized,
                display_name="Test Application",
                command=("test-app.exe",),
                source="test",
                executable="test-app.exe",
                app_id=None,
            )

        raise ResourceNotFound(
            f"Application '{name}' not found in test resolver."
        )


def test_resolve_existing_file(tmp_path) -> None:
    test_file = tmp_path / "example.txt"

    test_file.write_text(
        "ULTRON resource discovery test",
        encoding="utf-8",
    )

    resource = ResourceDiscovery().resolve(
        str(test_file)
    )

    assert resource.kind == "file"
    assert resource.path == str(test_file.resolve())
    assert resource.exists is True
    assert resource.source == "filesystem"


def test_resolve_existing_directory(tmp_path) -> None:
    resource = ResourceDiscovery().resolve(
        str(tmp_path)
    )

    assert resource.kind == "directory"
    assert resource.path == str(tmp_path.resolve())
    assert resource.exists is True
    assert resource.source == "filesystem"


def test_resolve_system_drive() -> None:
    system_drive = os.environ.get("SystemDrive")

    if not system_drive:
        pytest.skip(
            "Windows SystemDrive environment variable unavailable."
        )

    resource = ResourceDiscovery().resolve(
        f"{system_drive}\\"
    )

    assert resource.kind == "drive"
    assert resource.path == f"{system_drive.upper()}\\"
    assert resource.exists is True


def test_resolve_url() -> None:
    resource = ResourceDiscovery().resolve(
        "https://github.com"
    )

    assert resource.kind == "url"
    assert resource.uri == "https://github.com"
    assert resource.source == "url"
    assert resource.exists is True


def test_resolve_uri() -> None:
    resource = ResourceDiscovery().resolve(
        "mailto:test@example.com"
    )

    assert resource.kind == "uri"
    assert resource.uri == "mailto:test@example.com"
    assert resource.source == "uri"
    assert resource.exists is True


def test_resolve_settings_system_uri_alias() -> None:
    resolver = ResourceDiscovery(
        applications=StubApplicationDiscovery()
    )

    resource = resolver.resolve(
        "Settings"
    )

    assert resource.kind == "uri"
    assert resource.uri == "ms-settings:"
    assert resource.target == "ms-settings:"
    assert resource.source == "windows-system-uri"
    assert resource.exists is True


def test_resolve_application() -> None:
    resolver = ResourceDiscovery(
        applications=StubApplicationDiscovery()
    )

    resource = resolver.resolve(
        "Test Application"
    )

    assert resource.kind == "application"
    assert resource.application is not None
    assert resource.application.display_name == "Test Application"
    assert resource.application.source == "test"
    assert resource.exists is True


def test_resolve_unknown_resource() -> None:
    resolver = ResourceDiscovery(
        applications=StubApplicationDiscovery()
    )

    with pytest.raises(ResourceNotFound):
        resolver.resolve(
            "this-resource-definitely-does-not-exist"
        )