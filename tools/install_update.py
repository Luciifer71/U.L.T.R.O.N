"""Install an ULTRON source update after checking the expected file versions."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone


def digest(data: bytes) -> str:
    text = data.decode('utf-8-sig').replace('\r\n', '\n')
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def install(bundle: Path, target: Path) -> Path | None:
    manifest = json.loads((bundle / 'manifest.json').read_text())
    changes = []
    for name, checks in manifest.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe manifest path.')
        destination = target / relative
        if not destination.resolve().is_relative_to(target.resolve()):
            raise ValueError('Target escapes the project directory.')
        payload = (bundle / 'files' / relative).read_bytes()
        if digest(payload) != checks['new']:
            raise ValueError(f'Update file failed integrity check: {name}')
        previous = destination.read_bytes() if destination.exists() else None
        actual = digest(previous) if previous is not None else None
        if actual == checks['new']:
            continue
        if actual != checks['old']:
            raise ValueError(f'Unexpected local version of {name}. Nothing was changed. Share git diff for this file.')
        changes.append((destination, relative, payload, previous))
    if not changes:
        print('This update is already installed.')
        return None
    backup = bundle / ('backup-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir()
    # Write every backup before changing the repository.
    for _, relative, _, previous in changes:
        if previous is not None:
            saved = backup / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(previous)
    applied = []
    try:
        for destination, _, payload, previous in changes:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
            try:
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
            applied.append((destination, previous))
    except BaseException:
        for destination, previous in reversed(applied):
            if previous is None:
                destination.unlink(missing_ok=True)
            else:
                destination.write_bytes(previous)
        raise
    print(f'Installed {len(changes)} source files. Backup: {backup}')
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=Path.cwd())
    args = parser.parse_args()
    target = args.target.resolve()
    if not (target / 'brain_agent.py').is_file():
        parser.error('--target must be the Ultron-core project directory')
    try:
        install(Path(__file__).resolve().parent, target)
    except (OSError, ValueError) as exc:
        print(f'Update stopped: {exc}')
        return 1
    print('Run: .\\.venv\\Scripts\\python.exe .\\verify_ultron.py --speech')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
