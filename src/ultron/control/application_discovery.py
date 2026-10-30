"""Dynamic Windows application discovery and resolution."""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

try:
    import winreg  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - Windows-only module.
    winreg = None  # type: ignore[assignment]

from .models import CapabilityError, ResolvedApplication


class ApplicationNotFound(CapabilityError):
    """Raised when an application cannot be safely resolved."""


class ApplicationAmbiguous(CapabilityError):
    """Raised when an application request has multiple plausible matches."""


class ApplicationDiscovery:
    """Discover installed applications without relying on LLM-created commands."""

    _APP_PATH_EXECUTABLES = {
        "microsoft edge": "msedge.exe",
        "edge": "msedge.exe",
        "google chrome": "chrome.exe",
        "chrome": "chrome.exe",
        "notion": "notion.exe",
        "spotify": "spotify.exe",
        "discord": "discord.exe",
        "visual studio code": "Code.exe",
        "vs code": "Code.exe",
        "vscode": "Code.exe",
    }

    _COMMON_EXECUTABLES = {
        "calculator": "calc.exe",
        "calc": "calc.exe",
        "task manager": "taskmgr.exe",
        "taskmgr": "taskmgr.exe",
        "file explorer": "explorer.exe",
        "explorer": "explorer.exe",
        "notepad": "notepad.exe",
        "command prompt": "cmd.exe",
        "cmd": "cmd.exe",
        "powershell": "powershell.exe",
        "terminal": "wt.exe",
        "windows terminal": "wt.exe",
    }

    def resolve(
        self,
        requested_name: str,
    ) -> ResolvedApplication:
        """Resolve a human/LLM application name to a safe launch target."""

        normalized = self.normalize_name(requested_name)

        if not normalized:
            raise ApplicationNotFound(
                "No application name was provided."
            )

        # --------------------------------------------------------------
        # 1. Core Windows executables
        # --------------------------------------------------------------
        executable = self._COMMON_EXECUTABLES.get(
            normalized
        )

        if executable:
            located = (
                shutil.which(executable)
                or executable
            )

            return ResolvedApplication(
                requested_name=requested_name,
                display_name=self._display_name(normalized),
                command=(os.path.abspath(located),),
                source="windows-system-executable",
                executable=Path(located).name,
            )

        # --------------------------------------------------------------
        # 2. PATH lookup
        #
        # IMPORTANT:
        # WindowsApps entries can be execution aliases for packaged apps.
        # Do not treat those aliases as normal desktop executables.
        # We deliberately skip them and continue to AppX discovery below.
        # --------------------------------------------------------------
        compact_name = re.sub(
            r"\s+",
            "",
            normalized,
        )

        path_candidates = [
            normalized,
            f"{normalized}.exe",
            compact_name,
            f"{compact_name}.exe",
        ]

        for candidate in path_candidates:
            located = shutil.which(candidate)

            if not located:
                continue

            located = os.path.abspath(located)

            if self._is_windows_execution_alias(
                located
            ):
                continue

            return ResolvedApplication(
                requested_name=requested_name,
                display_name=self._display_name(normalized),
                command=(located,),
                source="path",
                executable=os.path.basename(located),
            )

        # --------------------------------------------------------------
        # 3. Known deterministic installation paths
        # --------------------------------------------------------------
        for candidate in self._known_paths(
            normalized
        ):
            expanded = os.path.abspath(
                os.path.expandvars(
                    os.path.expanduser(candidate)
                )
            )

            if os.path.isfile(expanded):
                return ResolvedApplication(
                    requested_name=requested_name,
                    display_name=self._display_name(normalized),
                    command=(expanded,),
                    source="known-installation-path",
                    executable=os.path.basename(expanded),
                )

        # --------------------------------------------------------------
        # 4. Windows App Paths registry
        # --------------------------------------------------------------
        registry_match = self._resolve_app_paths(
            normalized
        )

        if registry_match:
            return ResolvedApplication(
                requested_name=requested_name,
                display_name=self._display_name(normalized),
                command=(registry_match,),
                source="app-paths-registry",
                executable=os.path.basename(registry_match),
            )

        # --------------------------------------------------------------
        # 5. Genuine AppX / MSIX application
        # --------------------------------------------------------------
        start_apps = self.list_start_apps()

        packaged = self._resolve_packaged_app(
            normalized,
            start_apps,
        )

        if packaged:
            return packaged

        # --------------------------------------------------------------
        # 6. Legacy / Start Menu fallback
        # --------------------------------------------------------------
        start_menu = self._best_start_app_match(
            normalized,
            start_apps,
        )

        if start_menu:
            display_name, app_id = start_menu

            return ResolvedApplication(
                requested_name=requested_name,
                display_name=display_name,
                command=(
                    "explorer.exe",
                    f"shell:AppsFolder\\{app_id}",
                ),
                source="windows-start-menu",
                executable="explorer.exe",
                app_id=app_id,
            )

        raise ApplicationNotFound(
            f"Application '{requested_name}' could not be "
            "resolved to an installed Windows application."
        )

    # ------------------------------------------------------------------
    # Windows execution alias detection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_windows_execution_alias(
        path: str,
    ) -> bool:
        """
        Return True when a resolved PATH executable is a WindowsApps
        execution alias.

        Example:
            C:\\Users\\Krish\\AppData\\Local\\Microsoft\\WindowsApps\\spotify.EXE
        """

        normalized_path = os.path.normcase(
            os.path.abspath(path)
        )

        windowsapps_path = os.path.normcase(
            os.path.abspath(
                os.path.join(
                    os.getenv(
                        "LOCALAPPDATA",
                        "",
                    ),
                    "Microsoft",
                    "WindowsApps",
                )
            )
        )

        try:
            return os.path.commonpath(
                [
                    normalized_path,
                    windowsapps_path,
                ]
            ) == windowsapps_path
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # Name normalization
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_name(
        value: str,
    ) -> str:
        value = str(
            value or ""
        ).strip().lower()

        value = re.sub(
            r"\.exe$",
            "",
            value,
        )

        value = re.sub(
            r"[^a-z0-9]+",
            " ",
            value,
        )

        return " ".join(
            value.split()
        )

    @staticmethod
    def _display_name(
        normalized: str,
    ) -> str:
        names = {
            "calculator": "Calculator",
            "calc": "Calculator",
            "task manager": "Task Manager",
            "taskmgr": "Task Manager",
            "file explorer": "File Explorer",
            "explorer": "File Explorer",
            "microsoft edge": "Microsoft Edge",
            "edge": "Microsoft Edge",
            "google chrome": "Google Chrome",
            "chrome": "Google Chrome",
            "visual studio code": "Visual Studio Code",
            "vs code": "Visual Studio Code",
            "vscode": "Visual Studio Code",
            "spotify": "Spotify",
            "notion": "Notion",
        }

        return names.get(
            normalized,
            normalized.title(),
        )

    # ------------------------------------------------------------------
    # Known installation paths
    # ------------------------------------------------------------------

    @staticmethod
    def _known_paths(
        normalized: str,
    ) -> Iterable[str]:
        appdata = os.getenv(
            "LOCALAPPDATA",
            "",
        )

        program_files = os.getenv(
            "ProgramFiles",
            r"C:\Program Files",
        )

        program_files_x86 = os.getenv(
            "ProgramFiles(x86)",
            r"C:\Program Files (x86)",
        )

        roaming = os.getenv(
            "APPDATA",
            "",
        )

        mapping = {
            "microsoft edge": [
                rf"{program_files}\Microsoft\Edge\Application\msedge.exe",
                rf"{program_files_x86}\Microsoft\Edge\Application\msedge.exe",
                rf"{appdata}\Microsoft\Edge\Application\msedge.exe",
            ],
            "edge": [
                rf"{program_files}\Microsoft\Edge\Application\msedge.exe",
                rf"{program_files_x86}\Microsoft\Edge\Application\msedge.exe",
                rf"{appdata}\Microsoft\Edge\Application\msedge.exe",
            ],
            "notion": [
                rf"{appdata}\Programs\Notion\Notion.exe",
                rf"{appdata}\Notion\Notion.exe",
                rf"{program_files}\Notion\Notion.exe",
            ],
            "spotify": [
                rf"{roaming}\Spotify\Spotify.exe",
                rf"{appdata}\Spotify\Spotify.exe",
            ],
            "google chrome": [
                rf"{program_files}\Google\Chrome\Application\chrome.exe",
                rf"{program_files_x86}\Google\Chrome\Application\chrome.exe",
                rf"{appdata}\Google\Chrome\Application\chrome.exe",
            ],
            "chrome": [
                rf"{program_files}\Google\Chrome\Application\chrome.exe",
                rf"{program_files_x86}\Google\Chrome\Application\chrome.exe",
                rf"{appdata}\Google\Chrome\Application\chrome.exe",
            ],
            "visual studio code": [
                rf"{appdata}\Programs\Microsoft VS Code\Code.exe",
                rf"{program_files}\Microsoft VS Code\Code.exe",
            ],
            "vs code": [
                rf"{appdata}\Programs\Microsoft VS Code\Code.exe",
                rf"{program_files}\Microsoft VS Code\Code.exe",
            ],
            "vscode": [
                rf"{appdata}\Programs\Microsoft VS Code\Code.exe",
                rf"{program_files}\Microsoft VS Code\Code.exe",
            ],
        }

        return mapping.get(
            normalized,
            (),
        )

    # ------------------------------------------------------------------
    # Start Menu enumeration
    # ------------------------------------------------------------------

    def list_start_apps(
        self,
    ) -> list[tuple[str, str]]:
        """Return Start Menu application names and AppIDs."""

        if os.name != "nt":
            return []

        script = (
            "Get-StartApps | "
            "Select-Object Name,AppID | "
            "ConvertTo-Json -Compress"
        )

        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    script,
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (
            OSError,
            subprocess.SubprocessError,
        ):
            return []

        if (
            result.returncode != 0
            or not result.stdout.strip()
        ):
            return []

        try:
            raw = json.loads(
                result.stdout
            )
        except json.JSONDecodeError:
            return []

        if isinstance(raw, dict):
            raw = [raw]

        apps: list[tuple[str, str]] = []

        for item in (
            raw if isinstance(raw, list) else []
        ):
            if not isinstance(item, dict):
                continue

            name = str(
                item.get(
                    "Name",
                    "",
                )
            ).strip()

            app_id = str(
                item.get(
                    "AppID",
                    "",
                )
            ).strip()

            if name and app_id:
                apps.append(
                    (
                        name,
                        app_id,
                    )
                )

        return apps

    # ------------------------------------------------------------------
    # AppX / MSIX package enumeration
    # ------------------------------------------------------------------

    def list_packaged_apps(
        self,
    ) -> list[dict[str, str]]:
        """
        Enumerate installed AppX/MSIX application identities.

        The canonical AUMID is:

            PackageFamilyName!ApplicationId
        """

        if os.name != "nt":
            return []

        script = r"""
$rows = @()

foreach ($pkg in Get-AppxPackage) {
    try {
        $manifest = Get-AppxPackageManifest $pkg

        foreach ($app in @(
            $manifest.Package.Applications.Application
        )) {
            $applicationId = [string]$app.Id

            if ([string]::IsNullOrWhiteSpace($applicationId)) {
                continue
            }

            $packageDisplayName = [string](
                $manifest.Package.Properties.DisplayName
            )

            $applicationDisplayName = [string](
                $app.VisualElements.DisplayName
            )

            $rows += [pscustomobject]@{
                Name = [string]$pkg.Name
                PackageFamilyName = [string]$pkg.PackageFamilyName
                InstallLocation = [string]$pkg.InstallLocation
                ApplicationId = $applicationId
                PackageDisplayName = $packageDisplayName
                ApplicationDisplayName = $applicationDisplayName
            }
        }
    }
    catch {
        continue
    }
}

$rows | ConvertTo-Json -Compress
"""

        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    script,
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (
            OSError,
            subprocess.SubprocessError,
        ):
            return []

        if (
            result.returncode != 0
            or not result.stdout.strip()
        ):
            return []

        try:
            raw = json.loads(
                result.stdout
            )
        except json.JSONDecodeError:
            return []

        if isinstance(raw, dict):
            raw = [raw]

        apps: list[dict[str, str]] = []

        for item in (
            raw if isinstance(raw, list) else []
        ):
            if not isinstance(item, dict):
                continue

            family = str(
                item.get(
                    "PackageFamilyName",
                    "",
                )
            ).strip()

            application_id = str(
                item.get(
                    "ApplicationId",
                    "",
                )
            ).strip()

            if not family or not application_id:
                continue

            apps.append(
                {
                    "name": str(
                        item.get(
                            "Name",
                            "",
                        )
                    ).strip(),
                    "packageFamilyName": family,
                    "installLocation": str(
                        item.get(
                            "InstallLocation",
                            "",
                        )
                    ).strip(),
                    "applicationId": application_id,
                    "packageDisplayName": str(
                        item.get(
                            "PackageDisplayName",
                            "",
                        )
                    ).strip(),
                    "applicationDisplayName": str(
                        item.get(
                            "ApplicationDisplayName",
                            "",
                        )
                    ).strip(),
                    "aumid": (
                        f"{family}!{application_id}"
                    ),
                }
            )

        return apps

    # ------------------------------------------------------------------
    # Packaged application resolution
    # ------------------------------------------------------------------

    def _resolve_packaged_app(
        self,
        normalized: str,
        start_apps: list[tuple[str, str]],
    ) -> ResolvedApplication | None:
        packaged = self.list_packaged_apps()

        if not packaged:
            return None

        # --------------------------------------------------------------
        # Exact Start Menu name
        # --------------------------------------------------------------
        exact_start = next(
            (
                item
                for item in start_apps
                if self.normalize_name(
                    item[0]
                ) == normalized
            ),
            None,
        )

        # --------------------------------------------------------------
        # Rank real AppX package identities
        # --------------------------------------------------------------
        ranked: list[
            tuple[float, dict[str, str]]
        ] = []

        for app in packaged:
            score = self._packaged_match_score(
                normalized,
                app,
                start_hint=(
                    exact_start[0]
                    if exact_start
                    else None
                ),
            )

            if score > 0:
                ranked.append(
                    (
                        score,
                        app,
                    )
                )

        if not ranked:
            return None

        ranked.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        best_score, best_app = ranked[0]

        if best_score < 0.78:
            return None

        # --------------------------------------------------------------
        # Ambiguity guard
        # --------------------------------------------------------------
        if len(ranked) > 1:
            second_score, second_app = ranked[1]

            if (
                best_score - second_score < 0.12
                and self._package_identity_name(
                    best_app
                )
                != self._package_identity_name(
                    second_app
                )
            ):
                raise ApplicationAmbiguous(
                    f"Application '{normalized}' is ambiguous "
                    f"between "
                    f"'{self._package_identity_name(best_app)}' "
                    f"and "
                    f"'{self._package_identity_name(second_app)}'."
                )

        display_name = (
            exact_start[0]
            if exact_start
            else self._friendly_packaged_name(
                best_app
            )
        )

        return self._packaged_result(
            requested_name=normalized,
            app=best_app,
            display_name=display_name,
        )

    def _packaged_result(
        self,
        *,
        requested_name: str,
        app: dict[str, str],
        display_name: str,
    ) -> ResolvedApplication:
        """Build a validated packaged-app resolution."""

        aumid = (
            f"{app['packageFamilyName']}"
            f"!{app['applicationId']}"
        )

        return ResolvedApplication(
            requested_name=requested_name,
            display_name=display_name,
            command=(
                "explorer.exe",
                f"shell:AppsFolder\\{aumid}",
            ),
            source="windows-appx",
            executable=None,
            app_id=aumid,
        )

    def _packaged_match_score(
        self,
        normalized: str,
        app: dict[str, str],
        *,
        start_hint: str | None,
    ) -> float:
        candidates = [
            app.get("name", ""),
            app.get("packageDisplayName", ""),
            app.get("applicationDisplayName", ""),
            app.get("applicationId", ""),
            self._package_identity_name(app),
        ]

        normalized_candidates = [
            self.normalize_name(
                value
            )
            for value in candidates
            if value
            and not value.lower().startswith(
                "ms-resource:"
            )
        ]

        query_tokens = set(
            normalized.split()
        )

        best = 0.0

        for candidate in normalized_candidates:
            if not candidate:
                continue

            score = difflib.SequenceMatcher(
                None,
                normalized,
                candidate,
            ).ratio()

            candidate_tokens = set(
                candidate.split()
            )

            if (
                query_tokens
                and query_tokens.issubset(
                    candidate_tokens
                )
            ):
                score += 0.22

            elif query_tokens.intersection(
                candidate_tokens
            ):
                score += 0.06

            if (
                normalized in candidate
                or candidate in normalized
            ):
                score += 0.08

            best = max(
                best,
                score,
            )

        # Exact Start Menu match is a strong signal.
        if start_hint:
            if (
                self.normalize_name(
                    start_hint
                )
                == normalized
            ):
                best += 0.20

        return best

    @staticmethod
    def _package_identity_name(
        app: dict[str, str],
    ) -> str:
        """Turn a package identity into searchable words."""

        package_name = str(
            app.get(
                "name",
                "",
            )
        )

        package_name = re.sub(
            r"([a-z])([A-Z])",
            r"\1 \2",
            package_name,
        )

        package_name = package_name.replace(
            ".",
            " ",
        )

        return ApplicationDiscovery.normalize_name(
            package_name
        )

    @staticmethod
    def _friendly_packaged_name(
        app: dict[str, str],
    ) -> str:
        """Choose the best available packaged-app display name."""

        for key in (
            "packageDisplayName",
            "applicationDisplayName",
            "name",
        ):
            value = str(
                app.get(
                    key,
                    "",
                )
            ).strip()

            if (
                value
                and not value.lower().startswith(
                    "ms-resource:"
                )
            ):
                return value

        return (
            ApplicationDiscovery.normalize_name(
                app.get(
                    "name",
                    "",
                )
            ).title()
        )

    # ------------------------------------------------------------------
    # Start Menu fallback
    # ------------------------------------------------------------------

    def _best_start_app_match(
        self,
        normalized: str,
        apps: list[tuple[str, str]],
    ) -> tuple[str, str] | None:
        if not apps:
            return None

        normalized_apps = [
            (
                self.normalize_name(name),
                name,
                app_id,
            )
            for name, app_id in apps
        ]

        exact = next(
            (
                item
                for item in normalized_apps
                if item[0] == normalized
            ),
            None,
        )

        if exact:
            return exact[1], exact[2]

        query_tokens = set(
            normalized.split()
        )

        ranked: list[
            tuple[float, str, str]
        ] = []

        for candidate, display, app_id in normalized_apps:
            score = difflib.SequenceMatcher(
                None,
                normalized,
                candidate,
            ).ratio()

            candidate_tokens = set(
                candidate.split()
            )

            if (
                query_tokens
                and query_tokens.issubset(
                    candidate_tokens
                )
            ):
                score += 0.18

            elif query_tokens.intersection(
                candidate_tokens
            ):
                score += 0.05

            ranked.append(
                (
                    score,
                    display,
                    app_id,
                )
            )

        ranked.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        best = ranked[0]

        if best[0] < 0.80:
            return None

        if len(ranked) > 1:
            second = ranked[1]

            if best[0] - second[0] < 0.12:
                raise ApplicationAmbiguous(
                    f"Application '{normalized}' is ambiguous "
                    f"between '{best[1]}' and "
                    f"'{second[1]}'."
                )

        return best[1], best[2]

    # ------------------------------------------------------------------
    # Windows App Paths registry
    # ------------------------------------------------------------------

    def _resolve_app_paths(
        self,
        normalized: str,
    ) -> str | None:
        if (
            winreg is None
            or os.name != "nt"
        ):
            return None

        executable = (
            self._APP_PATH_EXECUTABLES.get(
                normalized
            )
        )

        if not executable:
            return None

        subkey = (
            r"Software\Microsoft\Windows\CurrentVersion"
            rf"\App Paths\{executable}"
        )

        roots = (
            winreg.HKEY_CURRENT_USER,
            winreg.HKEY_LOCAL_MACHINE,
        )

        views = (
            0,
            getattr(
                winreg,
                "KEY_WOW64_64KEY",
                0,
            ),
            getattr(
                winreg,
                "KEY_WOW64_32KEY",
                0,
            ),
        )

        for root in roots:
            for view in views:
                try:
                    with winreg.OpenKey(
                        root,
                        subkey,
                        0,
                        winreg.KEY_READ | view,
                    ) as key:
                        value, _ = (
                            winreg.QueryValueEx(
                                key,
                                "",
                            )
                        )

                except (
                    FileNotFoundError,
                    OSError,
                ):
                    continue

                if not isinstance(
                    value,
                    str,
                ):
                    continue

                value = value.strip().strip(
                    '"'
                )

                if os.path.isfile(value):
                    return os.path.abspath(
                        value
                    )

        return None