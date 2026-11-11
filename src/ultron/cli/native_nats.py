"""Run NATS natively on Windows instead of in Docker.

Docker Desktop often takes minutes to boot; nats-server.exe starts in well
under a second. ``install`` downloads one pinned official release once and
refuses it unless its SHA-256 matches; ``start`` runs it in the background with
``config/nats-server.native.conf`` (loopback only).

Usage: python run_ultron.py setup-nats
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
import subprocess
import sys
from urllib.request import urlopen
import zipfile

from ultron.paths import project_root

VERSION = '2.10.29'  # same as the Docker image in docker-compose.yml
ARCHIVE = f'nats-server-v{VERSION}-windows-amd64'
URL = f'https://github.com/nats-io/nats-server/releases/download/v{VERSION}/{ARCHIVE}.zip'
# From the release's SHA256SUMS file.
SHA256 = '98657bf4d5a9ce44168c019ba6894cda8e22e6adc8798edc05c168db7262de29'
MAX_DOWNLOAD = 64 * 1024 * 1024
CONFIG = Path('config') / 'nats-server.native.conf'


def executable(root: Path) -> Path:
    return root / 'tools' / 'nats' / 'nats-server.exe'


def find(root: Path) -> Path | None:
    path = executable(root)
    return path if path.is_file() else None


def verify(data: bytes) -> None:
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256:
        raise ValueError(f'NATS download failed its checksum (got {digest[:16]}…); nothing was installed.')


def extract(data: bytes, root: Path) -> Path:
    """Write only nats-server.exe and its licence to fixed paths (no archive paths are trusted)."""
    target = executable(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        wanted = {f'{ARCHIVE}/nats-server.exe': target, f'{ARCHIVE}/LICENSE': target.parent / 'LICENSE'}
        if f'{ARCHIVE}/nats-server.exe' not in names:
            raise ValueError('nats-server.exe is missing from the NATS archive.')
        for name, path in wanted.items():
            if name in names:
                temporary = path.with_suffix(path.suffix + '.part')
                temporary.write_bytes(archive.read(name))
                temporary.replace(path)
    return target


def install(root: Path, opener=urlopen) -> Path:
    with opener(URL, timeout=120) as response:
        data = response.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError('NATS download is unexpectedly large; nothing was installed.')
    verify(data)
    return extract(data, root)


def start(root: Path, exe: Path) -> subprocess.Popen:
    """Start NATS in the background. It keeps running after the launcher exits."""
    flags = 0
    if sys.platform == 'win32':
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    logs = root / 'runtime' / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen([str(exe), '-c', str(root / CONFIG), '-l', str(logs / 'nats-server.log')],
                            cwd=root, creationflags=flags, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    root = project_root()
    existing = find(root)
    if existing and '--force' not in sys.argv[1:]:
        print(f'Native NATS is already installed: {existing}')
        return 0
    print(f'Downloading NATS {VERSION} for Windows from the official release…', flush=True)
    try:
        path = install(root)
    except (OSError, ValueError) as error:
        print(f'Setup failed: {error}')
        return 1
    print(f'Installed {path} (checksum verified).')
    print('start-ultron.cmd now starts NATS directly; Docker is no longer needed for it.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
