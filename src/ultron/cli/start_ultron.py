"""Windows startup: check/start dependencies, then open ULTRON terminals."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import shutil
import socket
import subprocess
import sys
import time
import traceback
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

from ultron.paths import project_root

ROOT = project_root()
COMPONENTS = ('action_daemon', 'brain_agent', 'voice_listener')
LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1'}


class StartupError(RuntimeError):
    pass


def wait_for(check, description, timeout=120):
    deadline = time.monotonic() + timeout
    next_report = 0
    while True:
        result = check()
        if result:
            return result
        if time.monotonic() >= deadline:
            raise StartupError(f'Timed out waiting for {description}. Check its terminal or application.')
        if time.monotonic() >= next_report:
            print(f'Waiting for {description}...', flush=True)
            next_report = time.monotonic() + 10
        time.sleep(1)


def nats_ready(url):
    parsed = urlparse(url)
    if parsed.scheme != 'nats' or not parsed.hostname:
        raise StartupError('Launcher requires a nats:// NATS_URL.')
    try:
        with socket.create_connection((parsed.hostname, parsed.port or 4222), timeout=2) as connection:
            connection.settimeout(2)
            greeting = b''
            while len(greeting) < 5:
                chunk = connection.recv(5 - len(greeting))
                if not chunk:
                    return False
                greeting += chunk
            return greeting == b'INFO '
    except OSError:
        return False


def ollama_models(host):
    # Local dependency probes do not use machine-wide HTTP proxy settings.
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(host.rstrip('/') + '/api/tags', timeout=3) as response:
            data = json.load(response)
        models = data.get('models')
        return data if isinstance(models, list) else None
    except (OSError, ValueError):
        return None


def find_executable(name, candidates=()):
    found = shutil.which(name)
    if found:
        return found
    for path in candidates:
        if path.is_file():
            return str(path)
    raise StartupError(f'{name} was not found. Install it or add its location to PATH.')


def start_console(command):
    return subprocess.Popen(command, cwd=ROOT, creationflags=subprocess.CREATE_NEW_CONSOLE)


def ensure_nats(url):
    if nats_ready(url):
        print('NATS is already reachable.', flush=True)
        return
    parsed = urlparse(url)
    if parsed.hostname not in LOCAL_HOSTS or (parsed.port or 4222) != 4222:
        raise StartupError('Configured NATS server is unavailable; this launcher only starts local NATS on port 4222.')
    docker = find_executable('docker.exe')
    def docker_ready():
        try:
            return subprocess.run([docker, 'info', '--format', '{{.ServerVersion}}'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5).returncode == 0
        except subprocess.TimeoutExpired:
            return False
    if not docker_ready():
        desktop = find_executable('Docker Desktop.exe', [
            Path(os.environ.get('PROGRAMFILES', r'C:\Program Files')) / 'Docker' / 'Docker' / 'Docker Desktop.exe',
            Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'DockerDesktop' / 'Docker Desktop.exe',
        ])
        print('Starting Docker Desktop...', flush=True)
        subprocess.Popen([desktop])
        wait_for(docker_ready, 'Docker engine')
    print('Starting the project NATS container...', flush=True)
    result = subprocess.run([docker, 'compose', 'up', '-d', '--no-recreate', '--pull', 'never', 'nats'],
                            cwd=ROOT, timeout=90)
    if result.returncode:
        raise StartupError('Docker Compose could not start NATS. Review the output above; the NATS image must already be installed.')
    wait_for(lambda: nats_ready(url), 'NATS server', timeout=30)


def ensure_ollama(host, model):
    parsed = urlparse(host)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        raise StartupError('OLLAMA_HOST must be an http:// or https:// URL.')
    data = ollama_models(host)
    if data is None:
        if parsed.hostname not in LOCAL_HOSTS:
            raise StartupError('Configured remote Ollama server is unavailable. Local startup would not repair that connection.')
        executable = find_executable('ollama.exe', [
            Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Ollama' / 'ollama.exe',
        ])
        print('Starting Ollama server...', flush=True)
        start_console([executable, 'serve'])
        data = wait_for(lambda: ollama_models(host), 'Ollama server', timeout=60)
    available = {entry.get('name', entry.get('model', '')) for entry in data['models']}
    if model not in available:
        raise StartupError(f'Required model {model!r} is missing. Install it once with: ollama pull {model}')
    print(f'Ollama is reachable; model {model} is installed.', flush=True)


def running_components(root, processes):
    import psutil
    running = set()
    for process in processes:
        try:
            info = process.info
            command = info.get('cmdline') or []
            cwd = info.get('cwd')
            if not cwd or Path(cwd).resolve() != root.resolve():
                continue
            for component in COMPONENTS:
                if '--component' in command:
                    index = command.index('--component') + 1
                    if index < len(command) and command[index] == component:
                        running.add(component)
                if ('ultron.agents.' + component in command
                        or any(Path(argument).name == 'run_ultron.py' and index + 1 < len(command)
                               and command[index + 1] == component for index, argument in enumerate(command))):
                    running.add(component)
                if any(Path(argument).name == component + '.py' for argument in command[1:]):
                    running.add(component)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    return running


def warm_ollama(host, model):
    """Exercise selected inference before starting a fresh microphone session."""
    from ultron.core.ollama_runtime import OllamaRuntimeConfig
    try:
        config = OllamaRuntimeConfig.from_env(host=host, model=model)
        options = {'num_predict': 8, 'temperature': 0}
        for key, value in (('num_ctx', config.num_ctx), ('temperature', config.temperature),
                           ('seed', config.seed)):
            if value is not None:
                options[key] = value
        payload = {'model': model, 'messages': [{'role': 'user', 'content': 'Count from one to eight.'}],
                   'stream': False, 'keep_alive': '10m', 'options': options}
        if config.think is not None:
            payload['think'] = config.think
        request = Request(host.rstrip('/') + '/api/chat', data=json.dumps(payload).encode(),
                          headers={'Content-Type': 'application/json'}, method='POST')
        print(f'Warming {model} before microphone startup (up to 300 seconds)...', flush=True)
        started = time.monotonic()
        with build_opener(ProxyHandler({})).open(request, timeout=300) as response:
            result = json.load(response)
        if not isinstance(result, dict) or result.get('error') or result.get('done') is not True:
            raise ValueError('Ollama did not return a completed warmup response')
        timing = {'wall_seconds': round(time.monotonic() - started, 3)}
        for field in ('load_duration', 'prompt_eval_duration', 'eval_duration', 'eval_count'):
            value = result.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                timing[field.replace('_duration', '_seconds')] = round(value / 1e9, 3) if field.endswith('_duration') else value
        print('[WARMUP TIMING] ' + json.dumps(timing), flush=True)
        print(f'Model warmup complete in {time.monotonic() - started:.1f}s. Starting components.', flush=True)
    except (OSError, ValueError) as exc:
        raise StartupError(f'Model warmup failed; microphone not started: {exc}') from exc


@contextmanager
def startup_lock():
    # Serializes launch attempts for this checkout; never locks other projects.
    import msvcrt
    location = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ULTRON' / 'startup'
    location.mkdir(parents=True, exist_ok=True)
    identity = hashlib.sha256(str(ROOT).casefold().encode()).hexdigest()[:20]
    with (location / (identity + '.lock')).open('a+b') as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise StartupError('Another launcher is already starting this checkout.') from exc
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def run_component(component):
    from ultron.control.session_logs import capture_console
    with capture_console(ROOT, component):
        return _run_component(component)


def _run_component(component):
    # Keep the console open after an error, so diagnostic output is readable.
    os.chdir(ROOT)
    sys.argv = [component]
    code = 0
    try:
        runpy.run_module('ultron.agents.' + component, run_name='__main__')
    except KeyboardInterrupt:
        print('\nComponent stopped.')
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    except Exception:
        traceback.print_exc()
        code = 1
    try:
        input('\nComponent has stopped. Press Enter to close this window.')
    except (EOFError, KeyboardInterrupt):
        pass
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--component', choices=COMPONENTS, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if os.name != 'nt':
        print('This launcher currently supports Windows only.')
        return 1
    python = ROOT / '.venv' / 'Scripts' / 'python.exe'
    if not python.is_file():
        print('Project virtual environment is missing: .venv\\Scripts\\python.exe')
        return 1
    if Path(sys.executable).resolve() != python.resolve():
        return subprocess.call([str(python), str(ROOT / "run_ultron.py"), "start", *sys.argv[1:]])
    try:
        missing = [name for name in ('dotenv', 'psutil', 'keyboard', 'edge_tts', 'pygame', 'nats',
                                    'ollama', 'numpy', 'sounddevice', 'faster_whisper', 'ctranslate2')
                   if importlib.util.find_spec(name) is None]
        if missing:
            raise StartupError('Missing project packages: ' + ', '.join(missing) + '. Install the project requirements in .venv.')
        from dotenv import load_dotenv
        import psutil
        load_dotenv(ROOT / '.env', override=False)
        if args.component:
            return run_component(args.component)
        for component in COMPONENTS:
            if not (ROOT / 'src' / 'ultron' / 'agents' / (component + '.py')).is_file():
                raise StartupError(f'Missing source file: {component}.py')
        with startup_lock():
            ensure_nats(os.getenv('NATS_URL', 'nats://127.0.0.1:4222'))
            ensure_ollama(os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434'),
                          os.getenv('LLM_MODEL', 'qwen3:8b'))
            existing = running_components(ROOT, psutil.process_iter(['cmdline', 'cwd']))
            if not existing:
                warm_ollama(os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434'),
                            os.getenv('LLM_MODEL', 'qwen3:8b'))
            else:
                print('Existing components detected; warmup skipped. Stop all components for a fresh model trial.', flush=True)
            for component in COMPONENTS:
                if component in existing:
                    print(f'{component} is already running; skipped.', flush=True)
                    continue
                start_console([str(python), str(ROOT / "run_ultron.py"), "start", '--component', component])
                print(f'Launched {component}. Check its terminal for readiness.', flush=True)
        print('Wait for the voice listener to finish calibration and show STANDBY MODE.')
        print('Stop each component with Ctrl+C in its window. Docker and Ollama remain running.')
        return 0
    except (StartupError, OSError, subprocess.TimeoutExpired) as exc:
        print(f'Startup stopped: {exc}', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
