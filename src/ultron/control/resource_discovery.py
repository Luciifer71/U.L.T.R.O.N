"""Universal resource discovery for ULTRON.

This module resolves a user/LLM target into a typed resource without
performing the requested action.

Supported resource classes:

    application
    file
    directory
    drive
    url
    uri

The resolver does not bypass Windows permissions. Existing filesystem
permissions remain enforced by Windows and by the capability layer.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

from .application_discovery import ApplicationDiscovery
from .models import (
    CapabilityError,
    ResolvedResource,
)


class ResourceNotFound(CapabilityError):
    """Raised when a requested resource cannot be resolved."""


class ResourceDiscovery:
    """Resolve arbitrary user targets into structured resources."""

    _URL_SCHEMES = frozenset(
        {
            "http",
            "https",
            "ftp",
            "ftps",
        }
    )

    _COMMON_URI_SCHEMES = frozenset(
        {
            "mailto",
            "tel",
            "ms-settings",
            "ms-windows-store",
            "microsoft-edge",
            "steam",
            "discord",
            "zoommtg",
            "vscode",
            "git",
            "file",
        }
    )

    # Human-readable Windows system entry points that have a stable URI
    # contract but may collide with multiple AppX/MSIX package names.
    _SYSTEM_URI_ALIASES = {
        "settings": "ms-settings:",
        "system settings": "ms-settings:",
        "windows settings": "ms-settings:",
        "microsoft store": "ms-windows-store:",
        "store": "ms-windows-store:",
    }

    _KNOWN_FOLDER_ALIASES = {
        "desktop": "Desktop",
        "documents": "Documents",
        "document": "Documents",
        "downloads": "Downloads",
        "download": "Downloads",
        "pictures": "Pictures",
        "picture": "Pictures",
        "music": "Music",
        "videos": "Videos",
        "video": "Videos",
    }

    def __init__(
        self,
        *,
        applications: ApplicationDiscovery | None = None,
    ) -> None:
        self.applications = (
            applications
            or ApplicationDiscovery()
        )

    # ------------------------------------------------------------------
    # Public resolver
    # ------------------------------------------------------------------

    def resolve(
        self,
        requested: str,
    ) -> ResolvedResource:
        """Resolve a human-readable resource target."""

        original = str(
            requested or ""
        ).strip()

        if not original:
            raise ResourceNotFound(
                "No resource target was provided."
            )

        # --------------------------------------------------------------
        # 0. Stable Windows system URI aliases
        #
        # These semantic names must be resolved before generic AppX/MSIX
        # discovery because multiple Windows packages can expose names
        # that normalize to the same human request.
        # --------------------------------------------------------------
        system_uri = self._resolve_system_uri_alias(
            original
        )

        if system_uri:
            return system_uri

        # --------------------------------------------------------------
        # 1. Explicit URL / URI
        # --------------------------------------------------------------
        uri_resource = self._resolve_uri(
            original
        )

        if uri_resource:
            return uri_resource

        # --------------------------------------------------------------
        # 2. Windows drive
        #
        # This must be checked before generic filesystem resolution so a
        # root such as C:\ is classified specifically as a drive rather
        # than being collapsed into a generic directory. Full paths such as
        # C:\Windows still fall through to filesystem resolution because
        # they do not match the drive-only syntax.
        # --------------------------------------------------------------
        drive_resource = self._resolve_drive(
            original
        )

        if drive_resource:
            return drive_resource

        # --------------------------------------------------------------
        # 3. Existing filesystem path
        #
        # This happens before application resolution so something like:
        #
        #   C:\Games\Example
        #
        # is always treated as a filesystem resource.
        # --------------------------------------------------------------
        filesystem_resource = (
            self._resolve_filesystem_path(
                original
            )
        )

        if filesystem_resource:
            return filesystem_resource

        # --------------------------------------------------------------
        # 4. Known user-folder aliases
        # --------------------------------------------------------------
        folder_resource = (
            self._resolve_known_folder_alias(
                original
            )
        )

        if folder_resource:
            return folder_resource

        # --------------------------------------------------------------
        # 5. Application discovery
        #
        # This delegates to the universal application resolver that we
        # have already hardened and tested.
        # --------------------------------------------------------------
        try:
            application = self.applications.resolve(
                original
            )

            return ResolvedResource(
                requested=original,
                kind="application",
                target=application.display_name,
                application=application,
                source="application-discovery",
                exists=True,
            )

        except Exception as exc:
            raise ResourceNotFound(
                f"Resource '{original}' could not be resolved: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Stable Windows system URI aliases
    # ------------------------------------------------------------------

    def _resolve_system_uri_alias(
        self,
        value: str,
    ) -> ResolvedResource | None:
        normalized = self._normalize_text(
            value
        )

        uri = self._SYSTEM_URI_ALIASES.get(
            normalized
        )

        if not uri:
            return None

        return ResolvedResource(
            requested=value,
            kind="uri",
            target=uri,
            uri=uri,
            source="windows-system-uri",
            exists=True,
        )

    # ------------------------------------------------------------------
    # URI / URL resolution
    # ------------------------------------------------------------------

    def _resolve_uri(
        self,
        value: str,
    ) -> ResolvedResource | None:
        parsed = urlparse(
            value
        )

        scheme = (
            parsed.scheme.lower().strip()
        )

        if not scheme:
            return None

        # Windows drive paths are parsed by urlparse as schemes:
        #
        #     C:\something
        #
        # so explicitly exclude single-letter drive schemes here.
        if (
            len(scheme) == 1
            and scheme.isalpha()
            and re.match(
                r"^[A-Za-z]:",
                value,
            )
        ):
            return None

        # Standard web URL.
        if scheme in self._URL_SCHEMES:
            if not parsed.netloc:
                return None

            return ResolvedResource(
                requested=value,
                kind="url",
                target=value,
                uri=value,
                source="url",
                exists=True,
            )

        # Registered Windows / application URI.
        if (
            scheme in self._COMMON_URI_SCHEMES
            or self._looks_like_uri(value)
        ):
            return ResolvedResource(
                requested=value,
                kind="uri",
                target=value,
                uri=value,
                source="uri",
                exists=True,
            )

        return None

    @staticmethod
    def _looks_like_uri(
        value: str,
    ) -> bool:
        """
        Detect a syntactically plausible custom URI.

        We deliberately require:
          - a valid scheme
          - no whitespace before the scheme separator
        """

        return bool(
            re.match(
                r"^[A-Za-z][A-Za-z0-9+.-]*:",
                value,
            )
        )

    # ------------------------------------------------------------------
    # Filesystem resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_filesystem_path(
        value: str,
    ) -> ResolvedResource | None:
        expanded = os.path.expandvars(
            os.path.expanduser(value)
        )

        # Do not convert ordinary words such as "spotify" into a
        # relative path before application resolution.
        #
        # An explicit relative/absolute filesystem expression contains
        # one of these path indicators.
        looks_like_path = (
            os.path.isabs(expanded)
            or expanded.startswith(
                (
                    ".\\",
                    "../",
                    "..\\",
                    "./",
                    "\\\\",
                    "~/",
                    "~\\",
                )
            )
            or "\\" in expanded
            or "/" in expanded
        )

        if not looks_like_path:
            return None

        candidate = Path(
            expanded
        )

        try:
            resolved = candidate.resolve()
        except OSError:
            return None

        if not resolved.exists():
            return None

        if resolved.is_dir():
            return ResolvedResource(
                requested=value,
                kind="directory",
                target=str(resolved),
                path=str(resolved),
                source="filesystem",
                exists=True,
            )

        if resolved.is_file():
            return ResolvedResource(
                requested=value,
                kind="file",
                target=str(resolved),
                path=str(resolved),
                source="filesystem",
                exists=True,
            )

        return None

    # ------------------------------------------------------------------
    # Drive resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_drive(
        value: str,
    ) -> ResolvedResource | None:
        normalized = value.strip()

        match = re.fullmatch(
            r"([A-Za-z]):(?:\\)?",
            normalized,
        )

        if not match:
            return None

        drive = (
            f"{match.group(1).upper()}:\\"
        )

        if not os.path.exists(drive):
            raise ResourceNotFound(
                f"Drive '{drive}' does not exist."
            )

        if not os.path.isdir(drive):
            raise ResourceNotFound(
                f"Drive '{drive}' is not accessible."
            )

        return ResolvedResource(
            requested=value,
            kind="drive",
            target=drive,
            path=drive,
            source="windows-drive",
            exists=True,
        )

    # ------------------------------------------------------------------
    # Known user folders
    # ------------------------------------------------------------------

    def _resolve_known_folder_alias(
        self,
        value: str,
    ) -> ResolvedResource | None:
        normalized = self._normalize_text(
            value
        )

        known_name = (
            self._KNOWN_FOLDER_ALIASES.get(
                normalized
            )
        )

        if not known_name:
            return None

        path = self._known_folder_path(
            known_name
        )

        if not path:
            return None

        resolved = Path(
            path
        ).resolve()

        if not resolved.exists():
            return None

        return ResolvedResource(
            requested=value,
            kind="directory",
            target=str(resolved),
            path=str(resolved),
            source="windows-known-folder",
            exists=True,
        )

    @staticmethod
    def _known_folder_path(
        name: str,
    ) -> str | None:
        """
        Resolve common per-user folders using the current Windows user
        environment.

        These are fallbacks; redirected Windows folders can later be
        migrated to SHGetKnownFolderPath for complete system fidelity.
        """

        user_profile = os.getenv(
            "USERPROFILE"
        )

        if not user_profile:
            return None

        mapping = {
            "Desktop": (
                os.path.join(
                    user_profile,
                    "Desktop",
                )
            ),
            "Documents": (
                os.path.join(
                    user_profile,
                    "Documents",
                )
            ),
            "Downloads": (
                os.path.join(
                    user_profile,
                    "Downloads",
                )
            ),
            "Pictures": (
                os.path.join(
                    user_profile,
                    "Pictures",
                )
            ),
            "Music": (
                os.path.join(
                    user_profile,
                    "Music",
                )
            ),
            "Videos": (
                os.path.join(
                    user_profile,
                    "Videos",
                )
            ),
        }

        return mapping.get(
            name
        )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_text(
        value: str,
    ) -> str:
        value = str(
            value or ""
        ).strip().lower()

        value = re.sub(
            r"\s+",
            " ",
            value,
        )

        return value
