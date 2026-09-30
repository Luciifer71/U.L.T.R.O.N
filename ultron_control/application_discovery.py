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


class ApplicationDiscovery:
    """Discover installed applications without relying on an LLM-created command."""

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

    def resolve(self, requested_name: str) -> ResolvedApplication:
        normalized = self.normalize_name(requested_name)
        if not normalized:
            raise ApplicationNotFound("No application name was provided.")

        # 1. Common Windows system executables. This is intentionally small;
        # everything else is discovered dynamically.
        common = {
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
        executable = common.get(normalized)
        if executable:
            located = shutil.which(executable) or executable
            return ResolvedApplication(
                requested_name=requested_name,
                display_name=self._display_name(normalized),
                command=(located,),
                source="windows-system-executable",
                executable=Path(located).name,
            )

        # 2. PATH lookup for normal desktop tools.
        path_candidates = [
            normalized,
            f"{normalized}.exe",
            re.sub(r"\s+", "", normalized),
            f"{re.sub(r'\s+', '', normalized)}.exe",
        ]
        for candidate in path_candidates:
            located = shutil.which(candidate)
            if located:
                return ResolvedApplication(
                    requested_name=requested_name,
                    display_name=self._display_name(normalized),
                    command=(os.path.abspath(located),),
                    source="path",
                    executable=os.path.basename(located),
                )

        # 3. Known installation paths provide deterministic resolution for a
        # few popular apps but are only a fast path, not the registry.
        known_paths = self._known_paths(normalized)
        for candidate in known_paths:
            expanded = os.path.abspath(os.path.expandvars(os.path.expanduser(candidate)))
            if os.path.isfile(expanded):
                return ResolvedApplication(
                    requested_name=requested_name,
                    display_name=self._display_name(normalized),
                    command=(expanded,),
                    source="known-installation-path",
                    executable=os.path.basename(expanded),
                )

        # 4. Windows App Paths registry.
        registry_match = self._resolve_app_paths(normalized)
        if registry_match:
            return ResolvedApplication(
                requested_name=requested_name,
                display_name=self._display_name(normalized),
                command=(registry_match,),
                source="app-paths-registry",
                executable=os.path.basename(registry_match),
            )

        # 5. Dynamic Start Menu enumeration. This is the scalable part: the
        # user does not need to manually register every installed application.
        start_apps = self.list_start_apps()
        match = self._best_start_app_match(normalized, start_apps)
        if match:
            display_name, app_id = match
            return ResolvedApplication(
                requested_name=requested_name,
                display_name=display_name,
                command=("explorer.exe", f"shell:AppsFolder\\{app_id}"),
                source="windows-apps-folder",
                app_id=app_id,
            )

        raise ApplicationNotFound(
            f"Application '{requested_name}' could not be resolved to an installed Windows application."
        )

    @staticmethod
    def normalize_name(value: str) -> str:
        value = str(value or "").strip().lower()
        value = re.sub(r"\.exe$", "", value)
        value = re.sub(r"[^a-z0-9]+", " ", value)
        return " ".join(value.split())

    @staticmethod
    def _display_name(normalized: str) -> str:
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
        }
        return names.get(normalized, normalized.title())

    @staticmethod
    def _known_paths(normalized: str) -> Iterable[str]:
        appdata = os.getenv("LOCALAPPDATA", "")
        program_files = os.getenv("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.getenv("ProgramFiles(x86)", r"C:\Program Files (x86)")
        roaming = os.getenv("APPDATA", "")

        mapping = {
            "microsoft edge": [
                rf"{program_files}\\Microsoft\\Edge\\Application\\msedge.exe",
                rf"{program_files_x86}\\Microsoft\\Edge\\Application\\msedge.exe",
                rf"{appdata}\\Microsoft\\Edge\\Application\\msedge.exe",
            ],
            "edge": [
                rf"{program_files}\\Microsoft\\Edge\\Application\\msedge.exe",
                rf"{program_files_x86}\\Microsoft\\Edge\\Application\\msedge.exe",
                rf"{appdata}\\Microsoft\\Edge\\Application\\msedge.exe",
            ],
            "notion": [
                rf"{appdata}\\Programs\\Notion\\Notion.exe",
                rf"{appdata}\\Notion\\Notion.exe",
                rf"{program_files}\\Notion\\Notion.exe",
            ],
            "spotify": [
                rf"{roaming}\\Spotify\\Spotify.exe",
                rf"{appdata}\\Spotify\\Spotify.exe",
            ],
            "google chrome": [
                rf"{program_files}\\Google\\Chrome\\Application\\chrome.exe",
                rf"{program_files_x86}\\Google\\Chrome\\Application\\chrome.exe",
                rf"{appdata}\\Google\\Chrome\\Application\\chrome.exe",
            ],
            "chrome": [
                rf"{program_files}\\Google\\Chrome\\Application\\chrome.exe",
                rf"{program_files_x86}\\Google\\Chrome\\Application\\chrome.exe",
                rf"{appdata}\\Google\\Chrome\\Application\\chrome.exe",
            ],
            "visual studio code": [
                rf"{appdata}\\Programs\\Microsoft VS Code\\Code.exe",
                rf"{program_files}\\Microsoft VS Code\\Code.exe",
            ],
            "vs code": [
                rf"{appdata}\\Programs\\Microsoft VS Code\\Code.exe",
                rf"{program_files}\\Microsoft VS Code\\Code.exe",
            ],
            "vscode": [
                rf"{appdata}\\Programs\\Microsoft VS Code\\Code.exe",
                rf"{program_files}\\Microsoft VS Code\\Code.exe",
            ],
        }
        return mapping.get(normalized, ())

    def list_start_apps(self) -> list[tuple[str, str]]:
        if os.name != "nt":
            return []

        script = (
            "Get-StartApps | Select-Object Name,AppID | "
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
        except (OSError, subprocess.SubprocessError):
            return []

        if result.returncode != 0 or not result.stdout.strip():
            return []

        try:
            raw = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []

        if isinstance(raw, dict):
            raw = [raw]

        apps: list[tuple[str, str]] = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("Name", "")).strip()
            app_id = str(item.get("AppID", "")).strip()
            if name and app_id:
                apps.append((name, app_id))
        return apps

    def _best_start_app_match(
        self,
        normalized: str,
        apps: list[tuple[str, str]],
    ) -> tuple[str, str] | None:
        if not apps:
            return None

        normalized_apps = [
            (self.normalize_name(name), name, app_id)
            for name, app_id in apps
        ]

        exact = next(
            (item for item in normalized_apps if item[0] == normalized),
            None,
        )
        if exact:
            return exact[1], exact[2]

        query_tokens = set(normalized.split())
        best: tuple[float, str, str] | None = None

        for candidate, display, app_id in normalized_apps:
            score = difflib.SequenceMatcher(
                None,
                normalized,
                candidate,
            ).ratio()
            candidate_tokens = set(candidate.split())
            if query_tokens and query_tokens.issubset(candidate_tokens):
                score += 0.18
            elif query_tokens.intersection(candidate_tokens):
                score += 0.05

            if best is None or score > best[0]:
                best = score, display, app_id

        if best and best[0] >= 0.72:
            return best[1], best[2]

        return None

    def _resolve_app_paths(self, normalized: str) -> str | None:
        if winreg is None or os.name != "nt":
            return None

        executable = self._APP_PATH_EXECUTABLES.get(normalized)
        if not executable:
            return None

        subkey = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{executable}"
        roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
        views = (
            0,
            getattr(winreg, "KEY_WOW64_64KEY", 0),
            getattr(winreg, "KEY_WOW64_32KEY", 0),
        )

        for root in roots:
            for view in views:
                try:
                    with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ | view) as key:
                        value, _ = winreg.QueryValueEx(key, "")
                except (FileNotFoundError, OSError):
                    continue

                if not isinstance(value, str):
                    continue
                value = value.strip().strip('"')
                if os.path.isfile(value):
                    return os.path.abspath(value)

        return None
