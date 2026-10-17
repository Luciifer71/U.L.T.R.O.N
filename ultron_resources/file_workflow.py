"""Bounded, scoped file discovery. No content ingestion or fuzzy title correction."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys
import time
import unicodedata

from .catalog import AccessDenied, AmbiguousResource, ResourceError

MEDIA = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.mp3', '.wav', '.flac', '.m4a', '.ogg'}
DOCUMENTS = {'.pdf', '.txt', '.md', '.csv', '.docx', '.xlsx', '.pptx', '.png', '.jpg', '.jpeg', '.gif', '.webp'}
FOLDERS = {'downloads': 'Downloads', 'documents': 'Documents', 'desktop': 'Desktop',
           'videos': 'Videos', 'music': 'Music', 'pictures': 'Pictures'}


class FileSelectionRequired(AmbiguousResource):
    def __init__(self, paths, root):
        self.candidates = [{'path': str(path)} for path in paths]
        labels = '; '.join(str(path.relative_to(root)) for path in paths[:3])
        ResourceError.__init__(self, 'Several files match: ' + labels + '. Specify the exact filename or full path. Nothing was opened.')


def known_folder(name):
    key = str(name).casefold()
    if key not in FOLDERS:
        raise ResourceError('Specify Downloads, Documents, Desktop, Videos, Music or Pictures.')
    if sys.platform == 'win32':
        import winreg
        names = {'downloads': '{374DE290-123F-4565-9164-39C4925E467B}',
                 'documents': 'Personal', 'desktop': 'Desktop', 'videos': 'My Video',
                 'music': 'My Music', 'pictures': 'My Pictures'}
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as registry:
                value, kind = winreg.QueryValueEx(registry, names[key])
            if kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                raise ResourceError('The Windows folder configuration is not a path.')
            path = Path(os.path.expandvars(value))
            if not path.is_absolute():
                raise ResourceError('The Windows folder configuration is not an absolute path.')
            return path
        except FileNotFoundError:
            pass
    return Path.home() / FOLDERS[key]


def words(value):
    return re.findall(r'\w+', unicodedata.normalize('NFC', value).casefold(), flags=re.UNICODE)


def matches_name(path, query):
    # Explicit extensions require the complete filename. Title searches match
    # contiguous words, so Supergirl matches Supergirl.2026 but not Supergirl2.
    if Path(query).suffix:
        return path.name.casefold() == query.casefold()
    wanted, actual = words(query), words(path.stem)
    return bool(wanted) and any(actual[i:i + len(wanted)] == wanted for i in range(len(actual) - len(wanted) + 1))


@dataclass(frozen=True)
class PreparedFile:
    path: Path
    root: Path
    identity: tuple


def identity(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def prepare_file(service, query, folder, *, media_only=False, max_entries=5000, max_seconds=3):
    query = str(query).strip()
    if not query or len(query) > 240 or any(c in query for c in ('/', '\\', '\x00')) or query in {'.', '..'}:
        raise ResourceError('Give a filename or title, and a supported folder name.')
    if not 1 <= max_entries <= 5000 or not 0 < max_seconds <= 10:
        raise ValueError('Invalid file-search bounds.')
    policy = service.catalog.policy
    root = policy.resolve(known_folder(folder))
    if not root.is_dir():
        raise ResourceError('The requested folder does not exist.')
    suffixes = MEDIA if media_only else MEDIA | DOCUMENTS
    if Path(query).suffix and Path(query).suffix.casefold() not in suffixes:
        raise ResourceError('This workflow opens supported media or documents only; executable files require a separate explicit operation.')
    pending = [root]
    candidates = []
    count = 0
    deadline = time.monotonic() + max_seconds
    try:
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    count += 1
                    if count > max_entries or time.monotonic() > deadline:
                        raise ResourceError('The folder search was incomplete; specify an exact file path or a smaller scope. Nothing was opened.')
                    try:
                        path = policy.resolve(entry.path)
                    except AccessDenied:
                        continue  # Links, junctions and protected paths are outside searchable scope.
                    if not path.is_relative_to(root):
                        continue
                    if path.is_dir():
                        pending.append(path)
                    elif path.is_file() and path.suffix.casefold() in suffixes and matches_name(path, query):
                        candidates.append(path)
                        if len(candidates) >= 5:
                            raise FileSelectionRequired(candidates, root)
    except OSError as exc:
        raise ResourceError('The folder search could not be completed; check access or supply an exact file path. Nothing was opened.') from exc
    if not candidates:
        raise ResourceError(f"No matching supported file named '{query}' in {folder}. Nothing was opened.")
    if len(candidates) > 1:
        raise FileSelectionRequired(candidates, root)
    path = candidates[0]
    return PreparedFile(path, root, identity(path))


def open_prepared_file(service, prepared):
    path = service.catalog.policy.resolve(prepared.path)
    if not path.is_relative_to(prepared.root) or identity(path) != prepared.identity:
        raise ResourceError('The selected file changed after discovery; repeat the request. Nothing was opened.')
    return service.open(str(path), root=str(prepared.root))
