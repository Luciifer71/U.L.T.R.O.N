"""Filesystem capabilities for ULTRON.

Operations intentionally work with normal user permissions.  The capability
layer does not attempt to bypass Windows ACLs or elevation boundaries.
"""

from __future__ import annotations

import fnmatch
import os
import shutil
from pathlib import Path
from typing import Iterator

from .models import CapabilityError


class FilesystemCapability:
    """Structured file and directory access."""

    @staticmethod
    def resolve(path: str | os.PathLike[str]) -> Path:
        candidate = Path(os.path.expandvars(os.path.expanduser(str(path))))
        return candidate.resolve()

    def list_directory(self, path: str) -> list[dict[str, object]]:
        directory = self.resolve(path)
        if not directory.exists():
            raise CapabilityError(f"Directory does not exist: {directory}")
        if not directory.is_dir():
            raise CapabilityError(f"Not a directory: {directory}")

        entries: list[dict[str, object]] = []
        for entry in directory.iterdir():
            try:
                stat = entry.stat()
            except OSError:
                continue
            entries.append(
                {
                    "name": entry.name,
                    "path": str(entry),
                    "isDirectory": entry.is_dir(),
                    "isFile": entry.is_file(),
                    "size": stat.st_size if entry.is_file() else None,
                }
            )
        return sorted(entries, key=lambda x: (not bool(x["isDirectory"]), str(x["name"]).lower()))

    def search(
        self,
        root: str,
        pattern: str,
        *,
        max_results: int = 200,
    ) -> list[str]:
        base = self.resolve(root)
        if not base.exists():
            raise CapabilityError(f"Search root does not exist: {base}")

        results: list[str] = []
        for path in self._walk(base):
            if fnmatch.fnmatch(path.name.lower(), pattern.lower()) or pattern.lower() in path.name.lower():
                results.append(str(path))
                if len(results) >= max_results:
                    break
        return results

    def read_text(self, path: str, *, max_bytes: int = 2_000_000) -> str:
        target = self.resolve(path)
        if not target.is_file():
            raise CapabilityError(f"Not a file: {target}")
        if target.stat().st_size > max_bytes:
            raise CapabilityError(
                f"Refusing to load {target.stat().st_size} bytes; limit is {max_bytes}."
            )
        try:
            return target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise CapabilityError(f"File is not valid UTF-8 text: {target}") from exc

    def write_text(self, path: str, content: str) -> str:
        target = self.resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        return str(target)

    def copy(self, source: str, destination: str) -> str:
        src = self.resolve(source)
        dst = self.resolve(destination)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=False)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        return str(dst)

    def move(self, source: str, destination: str) -> str:
        src = self.resolve(source)
        dst = self.resolve(destination)
        dst.parent.mkdir(parents=True, exist_ok=True)
        return str(shutil.move(str(src), str(dst)))

    def delete(self, path: str) -> None:
        target = self.resolve(path)
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        else:
            raise FileNotFoundError(target)

    @staticmethod
    def _walk(root: Path) -> Iterator[Path]:
        for current, dirs, files in os.walk(root, followlinks=False):
            # Ignore common build/cache trees to keep searches responsive.
            dirs[:] = [
                d for d in dirs
                if d not in {".git", ".venv", "node_modules", "__pycache__", ".cache"}
            ]
            for file_name in files:
                yield Path(current) / file_name
