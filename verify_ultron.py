r"""Run the repository regression suite with the current Python interpreter.

Usage: .\.venv\Scripts\python.exe verify_ultron.py [--speech]
No live application actions are dispatched by this runner.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speech", action="store_true",
                        help="Also probe the configured speech runtime and microphone inventory.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if importlib.util.find_spec("pytest") is None:
        print("pytest is missing. Install it with this interpreter: python -m pip install pytest")
        return 2
    tests = sorted(path.name for path in root.glob("test_*.py"))
    if not tests:
        print("No regression test files found; verification cannot pass.")
        return 2
    print(f"Running {len(tests)} test files with {sys.executable}", flush=True)
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", *tests], cwd=root)
    if result.returncode:
        return result.returncode
    if args.speech:
        if importlib.util.find_spec("dotenv") is None:
            print("python-dotenv is missing; install the project's speech requirements.")
            return 2
        from dotenv import load_dotenv
        load_dotenv(root / ".env", override=False)
        result = subprocess.run([sys.executable, str(root / "speech_diagnostics.py")], cwd=root)
        if result.returncode:
            return result.returncode
    print("Requested checks passed. Live task completion and release readiness require separate evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
