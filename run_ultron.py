"""Run ULTRON from a source checkout without an editable install."""
from pathlib import Path
import os
import sys


def main():
    source = str(Path(__file__).resolve().parent / "src")
    sys.path.insert(0, source)
    # Speech and microphone probes use child interpreters.
    previous = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = source + (os.pathsep + previous if previous else "")
    from ultron.__main__ import main as dispatch
    return dispatch()


if __name__ == "__main__":
    raise SystemExit(main())
