"""Explicit resource operations using normal account permissions."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import subprocess
import sys
import threading

from .catalog import ResourceError


@dataclass(frozen=True)
class Outcome:
    success: bool
    operation: str
    target: str
    state: str
    message: str
    pid: int | None = None
    exit_code: int | None = None
    stdout: str = ''
    stderr: str = ''
    output_truncated: bool = False

    @property
    def data(self):
        return {'state': self.state, 'verification': 'not_observable' if self.state != 'completed' else 'exit_code',
                'target': self.target, 'pid': self.pid, 'exitCode': self.exit_code,
                'stdout': self.stdout, 'stderr': self.stderr, 'outputTruncated': self.output_truncated}

    @property
    def error(self):
        return None if self.success else self.message

    def to_dict(self):
        return asdict(self)


class PlatformAdapter:
    def __init__(self, platform=None):
        self.platform = platform or sys.platform

    def open(self, path, editor=None):
        path = str(path)
        if self.platform == 'win32':
            if editor:
                if editor.casefold() != 'notepad':
                    raise ResourceError('This editor adapter supports Notepad; other editors require an explicit application adapter.')
                executable = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'notepad.exe'
                process = subprocess.Popen([str(executable), path], shell=False)
                return process.pid
            os.startfile(path)
            return None
        if self.platform == 'darwin':
            command = ['/usr/bin/open']
            if editor:
                if editor.casefold() != 'textedit':
                    raise ResourceError('This editor adapter supports TextEdit; other editors require an explicit application adapter.')
                command += ['-a', 'TextEdit']
            result = subprocess.run([*command, path], shell=False, capture_output=True, text=True, timeout=15)
            if result.returncode:
                raise ResourceError(result.stderr.strip() or 'macOS did not accept the open request.')
            return None
        raise ResourceError('Native opening is supported on Windows and macOS only.')

    def launch(self, path, arguments=()):
        if self.platform == 'darwin' and path.suffix.casefold() == '.app':
            result = subprocess.run(['/usr/bin/open', str(path), '--args', *arguments], shell=False, capture_output=True, text=True, timeout=15)
            if result.returncode:
                raise ResourceError(result.stderr.strip() or 'macOS application launch failed.')
            return None
        if self.platform == 'win32' and path.suffix.casefold() == '.exe':
            process = subprocess.Popen([str(path), *arguments], cwd=path.parent, shell=False)
            return process.pid
        raise ResourceError('Launch requires a Windows .exe or macOS .app; scripts use run_script.')


class ResourceService:
    def __init__(self, catalog, adapter=None):
        self.catalog = catalog
        self.adapter = adapter or PlatformAdapter()

    @staticmethod
    def arguments(arguments):
        if not isinstance(arguments, (tuple, list)) or len(arguments) > 64 or any(not isinstance(arg, str) or '\x00' in arg or len(arg) > 4096 for arg in arguments):
            raise ResourceError('Arguments must be a bounded list of strings, not a shell command.')
        return list(arguments)

    def target(self, target, root=None, suffixes=None):
        resource = self.catalog.resolve(target, root=root, suffixes=suffixes)
        return self.catalog.policy.resolve(resource.path)

    def open(self, target, *, editor=None, root=None):
        path = self.target(target, root)
        if editor and not path.is_file():
            raise ResourceError('Opening with an editor requires a file.')
        if editor is None and path.suffix.casefold() in {'.exe', '.py', '.ps1', '.sh', '.bat', '.cmd', '.com', '.lnk', '.app', '.url', '.scr', '.msi', '.vbs', '.js'}:
            raise ResourceError('Executable resources require an explicit launch or run_script operation.')
        pid = self.adapter.open(path, editor)
        return Outcome(True, 'open', str(path), 'dispatched', 'The operating system accepted the open request; the visible result has not been verified.', pid)

    def launch(self, target, *, arguments=(), root=None):
        arguments = self.arguments(arguments)
        path = self.target(target, root, suffixes={'.exe', '.app'})
        pid = self.adapter.launch(path, arguments)
        state = 'launched' if pid is not None else 'dispatched'
        return Outcome(True, 'launch', str(path), state, 'Launch request accepted; application readiness has not been verified.', pid)

    def read_text(self, target, *, root=None, max_bytes=1_000_000):
        if not 1 <= max_bytes <= 1_000_000:
            raise ValueError('Read limit must be between 1 and 1000000 bytes.')
        path = self.target(target, root)
        with path.open('rb') as source:
            data = source.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ResourceError('File exceeds the text-read limit.')
        try:
            return data.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise ResourceError('This operation only reads UTF-8 text files.') from exc

    def run_script(self, target, *, arguments=(), root=None, timeout=30):
        if not isinstance(timeout, (int, float)) or not 0 < timeout <= 120:
            raise ValueError('Script timeout must be between 0 and 120 seconds.')
        arguments = self.arguments(arguments)
        suffixes = {'.py'}
        if self.adapter.platform == 'win32':
            suffixes.add('.ps1')
        elif self.adapter.platform == 'darwin':
            suffixes.add('.sh')
        path = self.target(target, root, suffixes=suffixes)
        if not path.is_file():
            raise ResourceError('Script target must be a file.')
        if path.suffix.casefold() == '.py':
            command = [sys.executable, str(path), *arguments]
        elif path.suffix.casefold() == '.ps1' and self.adapter.platform == 'win32':
            interpreter = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
            command = [str(interpreter), '-NoProfile', '-File', str(path), *arguments]
        elif path.suffix.casefold() == '.sh' and self.adapter.platform == 'darwin':
            command = ['/bin/sh', str(path), *arguments]
        else:
            raise ResourceError('Supported scripts: Python; PowerShell on Windows; POSIX shell on macOS.')
        # Drain both pipes continuously but retain only a bounded prefix.
        import psutil
        process = psutil.Popen(command, cwd=path.parent, shell=False,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        buffers = [bytearray(), bytearray()]
        truncated = [False, False]
        def drain(stream, index):
            try:
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    available = 20_000 - len(buffers[index])
                    buffers[index].extend(chunk[:available])
                    if len(chunk) > available:
                        truncated[index] = True
            except (OSError, ValueError):
                truncated[index] = True
            finally:
                stream.close()
        threads = [threading.Thread(target=drain, args=(stream, index), daemon=True)
                   for index, stream in enumerate((process.stdout, process.stderr))]
        for thread in threads:
            thread.start()
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, psutil.TimeoutExpired):
            timed_out = True
            try:
                descendants = process.children(recursive=True)
            except psutil.NoSuchProcess:
                descendants = []
            for descendant in descendants:
                try:
                    descendant.kill()
                except psutil.NoSuchProcess:
                    pass
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
            process.wait(timeout=5)
        finally:
            for index, thread in enumerate(threads):
                thread.join(timeout=1)
                if thread.is_alive():
                    truncated[index] = True
                    (process.stdout if index == 0 else process.stderr).close()
        out, err = [bytes(buffer).decode('utf-8', errors='replace') for buffer in buffers]
        success = not timed_out and process.returncode == 0
        return Outcome(success, 'run_script', str(path), 'completed' if success else 'failed',
                       'Script timed out.' if timed_out else f'Script exited with code {process.returncode}.',
                       process.pid, process.returncode, out, err, any(truncated))
