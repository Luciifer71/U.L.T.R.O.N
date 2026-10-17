"""Bounded console copies for launcher-managed Python components."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import logging
from logging.handlers import RotatingFileHandler
import sys


class ConsoleCopy:
    def __init__(self, console, handler):
        self.console = console
        self.handler = handler

    def write(self, text):
        count = self.console.write(text)
        if text:
            self.handler.handle(logging.LogRecord('console', logging.INFO, '', 0, text, (), None))
        return count

    def flush(self):
        self.console.flush()
        self.handler.flush()

    def __getattr__(self, name):
        return getattr(self.console, name)


@contextmanager
def capture_console(root, component):
    folder = root / 'runtime' / 'logs'
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / f'{component}.log', maxBytes=2 * 1024 * 1024,
                                  backupCount=1, encoding='utf-8')
    handler.terminator = ''
    try:
        with redirect_stdout(ConsoleCopy(sys.stdout, handler)), redirect_stderr(ConsoleCopy(sys.stderr, handler)):
            print(f'\n[SESSION START] {component} {datetime.now(timezone.utc).isoformat()}', flush=True)
            yield
    finally:
        handler.close()
