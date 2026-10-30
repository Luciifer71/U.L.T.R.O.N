"""Stable checkout paths; source migration never relocates personal data."""
from pathlib import Path
import os


def project_root():
    configured = os.environ.get("ULTRON_PROJECT_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    source_root = Path(__file__).resolve().parents[2]
    if (source_root / "run_ultron.py").is_file():
        return source_root
    raise RuntimeError("Set ULTRON_PROJECT_ROOT to your checkout when using an installed wheel.")
