"""Local metadata catalog. File contents are never ingested by indexing."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import uuid
import unicodedata


# macOS supplies these root-level aliases. Arbitrary user links remain denied.
_MACOS_SYSTEM_ALIASES = {Path('/var'): Path('/private/var'),
                         Path('/tmp'): Path('/private/tmp')}


def _is_macos_system_alias(path: Path) -> bool:
    if sys.platform != 'darwin' or path not in _MACOS_SYSTEM_ALIASES:
        return False
    expected = _MACOS_SYSTEM_ALIASES[path]
    try:
        # Check both the link itself and its physical destination; do not trust
        # an alias that has been redirected through an additional link.
        return (path.is_symlink()
                and path.parent / os.readlink(path) == expected
                and path.resolve(strict=True) == expected)
    except (OSError, RuntimeError):
        return False


class ResourceError(RuntimeError):
    pass


class AccessDenied(ResourceError):
    pass


class AmbiguousResource(ResourceError):
    def __init__(self, candidates):
        self.candidates = candidates
        paths = '; '.join(item['path'] for item in candidates[:5])
        super().__init__('Multiple exact matches; specify the folder or full path. Candidates: ' + paths)


def name_key(name: str) -> str:
    # Cosmetic normalization only: never change spelling or version numbers.
    name = re.sub(r'\.(?:exe|app|lnk|py|ps1|sh|txt|md|pdf|docx?|xlsx?|pptx?|csv|json|ya?ml|xml|png|jpe?g|mp[34])$', '', name, flags=re.I)
    normalized = unicodedata.normalize('NFC', name).casefold()
    return ''.join(char for char in normalized if unicodedata.category(char)[0] in {'L', 'N', 'M'})


@dataclass(frozen=True)
class Resource:
    id: str
    path: str
    name: str
    kind: str
    size: int
    mtime_ns: int

    def to_dict(self):
        return asdict(self)


class PathPolicy:
    def __init__(self, roots, protected=()):
        self.roots = tuple(Path(root).expanduser().resolve() for root in roots)
        if not self.roots:
            raise ValueError('At least one accessible root is required.')
        self.protected = tuple(Path(path).expanduser().resolve() for path in protected)

    def resolve(self, value, *, must_exist=True):
        original = Path(os.path.expandvars(str(value))).expanduser()
        # Do not follow symlinks/junctions into a different protected resource.
        for path in (original, *original.parents):
            if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                if not _is_macos_system_alias(path):
                    raise AccessDenied('Symlinks and junctions require an explicit supported resolution policy.')
        path = original.resolve(strict=must_exist)
        if not any(path == root or path.is_relative_to(root) for root in self.roots):
            raise AccessDenied('Target is outside the configured resource roots.')
        if any(path == blocked or path.is_relative_to(blocked) for blocked in self.protected):
            raise AccessDenied('Target is in a protected location.')
        parts = {part.casefold() for part in path.parts}
        if parts & {'windows', 'system volume information', '$recycle.bin', '.ssh', '.gnupg', '.aws', '.azure', '.kube', 'credentials', 'vault', 'keychains'}:
            raise AccessDenied('System or credential location is protected.')
        if path.name.casefold() in {'.env', 'login data', 'cookies', 'ntuser.dat', 'sam', 'security', 'system'}:
            raise AccessDenied('Credential or system data is protected.')
        return path


class ResourceCatalog:
    def __init__(self, database, policy):
        self.database = Path(database)
        self.policy = policy
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise ResourceError('Unsupported resource catalog schema version.')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS resources (
                    id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, root TEXT NOT NULL,
                    name TEXT NOT NULL, name_key TEXT NOT NULL, kind TEXT NOT NULL,
                    size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, scan TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS resource_name ON resources(name_key);
                CREATE INDEX IF NOT EXISTS resource_root ON resources(root);
                PRAGMA user_version=1;
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def resource(path):
        stat = path.stat()
        kind = 'directory' if path.is_dir() else 'file'
        if path.suffix.casefold() == '.app' and path.is_dir():
            kind = 'application'
        identity = hashlib.sha256(os.path.normcase(str(path)).encode()).hexdigest()
        return Resource(identity, str(path), path.name, kind, stat.st_size, stat.st_mtime_ns)

    def index(self, root, *, max_entries=100_000, max_seconds=30):
        if max_entries < 1 or max_seconds <= 0:
            raise ValueError('Scan limits must be positive.')
        root = self.policy.resolve(root)
        if not root.is_dir():
            raise ResourceError('Index root must be a directory.')
        scan = uuid.uuid4().hex
        deadline = time.monotonic() + max_seconds
        count = denied = errors = 0
        complete = True
        pending = [root]
        with self.connect() as db:
            while pending:
                if count >= max_entries or time.monotonic() >= deadline:
                    complete = False
                    break
                path = pending.pop()
                try:
                    path = self.policy.resolve(path)
                    if path == self.database:
                        continue
                    resource = self.resource(path)
                    db.execute('INSERT INTO resources VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET root=excluded.root,name=excluded.name,name_key=excluded.name_key,kind=excluded.kind,size=excluded.size,mtime_ns=excluded.mtime_ns,scan=excluded.scan',
                               (resource.id, resource.path, str(root), resource.name, name_key(resource.name), resource.kind, resource.size, resource.mtime_ns, scan))
                    count += 1
                    if path.is_dir() and resource.kind != 'application':
                        with os.scandir(path) as entries:
                            for entry in entries:
                                if len(pending) + count >= max_entries or time.monotonic() >= deadline:
                                    complete = False
                                    break
                                pending.append(Path(entry.path))
                except AccessDenied:
                    denied += 1
                except (OSError, RuntimeError):
                    errors += 1
                    complete = False
            if complete:
                db.execute('DELETE FROM resources WHERE root=? AND scan<>?', (str(root), scan))
        return {'root': str(root), 'indexed': count, 'protected_skipped': denied, 'errors': errors, 'complete': complete}

    def search(self, query, *, limit=20, root=None):
        if not 1 <= limit <= 100:
            raise ValueError('Search limit must be between 1 and 100.')
        key = name_key(query)
        if not key:
            raise ResourceError('A resource name is required.')
        scope = self.policy.resolve(root) if root else None
        condition, parameters = self._scope(scope)
        with self.connect() as db:
            rows = db.execute('SELECT * FROM resources WHERE name_key LIKE ?' + condition + ' ORDER BY (name_key=?) DESC, length(name_key), path LIMIT ?',
                              ['%' + key + '%', *parameters, key, 1000]).fetchall()
        candidates = []
        for row in rows:
            try:
                path = self.policy.resolve(row['path'])
                if scope and not (path == scope or path.is_relative_to(scope)):
                    continue
                current = self.resource(path)
                candidates.append(current)
            except (ResourceError, OSError):
                continue
            if len(candidates) == limit:
                break
        return candidates

    @staticmethod
    def _scope(scope):
        if scope is None:
            return '', []
        prefix = str(scope).rstrip(os.sep) + os.sep
        return ' AND (path=? OR substr(path,1,?)=?)', [str(scope), len(prefix), prefix]

    def resolve(self, target, *, root=None, suffixes=None):
        target = str(target).strip().strip('"')
        expanded = Path(os.path.expandvars(target)).expanduser()
        if expanded.is_absolute() or '/' in target or '\\' in target:
            path = self.policy.resolve(expanded)
            scope = self.policy.resolve(root) if root else None
            if scope and not (path == scope or path.is_relative_to(scope)):
                raise AccessDenied('Explicit target is outside the requested folder or drive.')
            if suffixes is not None and path.suffix.casefold() not in suffixes:
                raise ResourceError('Target type does not support the requested operation.')
            return self.resource(path)
        # Exact resolution must not infer uniqueness from a truncated search.
        condition, parameters = self._scope(self.policy.resolve(root) if root else None)
        exact = []
        with self.connect() as db:
            rows = db.execute('SELECT * FROM resources WHERE name_key=?' + condition + ' ORDER BY path',
                              [name_key(target), *parameters])
            for row in rows:
                if suffixes is not None and Path(row['path']).suffix.casefold() not in suffixes:
                    continue
                if Path(target).suffix and row['name'].casefold() != target.casefold():
                    continue
                try:
                    current = self.resource(self.policy.resolve(row['path']))
                except (ResourceError, OSError):
                    continue
                exact.append(current)
                if len(exact) >= 20:
                    break
        if len(exact) > 1:
            raise AmbiguousResource([item.to_dict() for item in exact])
        if not exact:
            raise ResourceError('No exact accessible catalog match. Refresh the index or specify the folder; a similar name is not auto-executed.')
        return exact[0]
