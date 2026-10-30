"""Compatibility entry point for the regression suite."""
from pathlib import Path
import runpy
import sys

if __name__ == "__main__":
    sys.argv.insert(1, "verify")
    runpy.run_path(str(Path(__file__).with_name("run_ultron.py")), run_name="__main__")
