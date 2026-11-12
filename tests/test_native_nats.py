"""Native NATS: checksum-verified install and a loopback-only configuration."""
import hashlib
import io
import re
from pathlib import Path
import zipfile

import pytest

from ultron.cli import native_nats

ROOT = Path(__file__).resolve().parents[1]


def archive(extra=()):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        z.writestr(f'{native_nats.ARCHIVE}/nats-server.exe', b'MZ fake server')
        z.writestr(f'{native_nats.ARCHIVE}/LICENSE', b'Apache-2.0')
        for name, data in extra:
            z.writestr(name, data)
    return buffer.getvalue()


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_download_with_a_wrong_checksum_installs_nothing(tmp_path):
    with pytest.raises(ValueError, match='checksum'):
        native_nats.install(tmp_path, opener=lambda url, timeout: Response(archive()))
    assert native_nats.find(tmp_path) is None


def test_verified_download_installs_only_the_server_and_licence(tmp_path, monkeypatch):
    data = archive(extra=[('../../evil.exe', b'x'), (f'{native_nats.ARCHIVE}/README.md', b'readme')])
    monkeypatch.setattr(native_nats, 'SHA256', hashlib.sha256(data).hexdigest())
    path = native_nats.install(tmp_path, opener=lambda url, timeout: Response(data))
    assert path == native_nats.find(tmp_path) == tmp_path / 'tools' / 'nats' / 'nats-server.exe'
    assert path.read_bytes() == b'MZ fake server'
    files = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob('*') if p.is_file())
    assert files == ['tools/nats/LICENSE', 'tools/nats/nats-server.exe']


def test_pinned_release_matches_the_docker_image():
    compose = (ROOT / 'docker-compose.yml').read_text()
    assert f'image: nats:{native_nats.VERSION}-' in compose
    assert native_nats.URL.startswith('https://github.com/nats-io/nats-server/releases/download/')
    assert re.fullmatch(r'[0-9a-f]{64}', native_nats.SHA256)


def _setting(text, key):
    match = re.search(rf'^\s*{key}:\s*"?([^"\n]+)"?', text, re.M)
    return match.group(1).strip() if match else None


def test_native_config_never_listens_on_the_network():
    """The bus has no authentication: natively it must bind to 127.0.0.1 only."""
    text = (ROOT / native_nats.CONFIG).read_text()
    assert _setting(text, 'listen') == '127.0.0.1:4222'
    assert _setting(text, 'http') == '127.0.0.1:8222'
    websocket = text[text.index('websocket'):]
    assert _setting(websocket, 'host') == '127.0.0.1'
    assert '0.0.0.0' not in re.sub(r'#.*', '', text)
    assert _setting(text, 'store_dir') == 'nats_data', 'relative to the project, not C:\\\\data'


def test_native_and_docker_configs_allow_the_same_ui_origins_and_ports():
    native = (ROOT / native_nats.CONFIG).read_text()
    docker = (ROOT / 'config' / 'nats-server.conf').read_text()
    origins = lambda text: re.findall(r'"(http://[^"]+)"', text)
    assert origins(native) == origins(docker)
    assert 'port: 9222' in native and 'port: 9222' in docker


def test_nats_is_started_in_its_own_window_not_as_a_hidden_child(monkeypatch, tmp_path):
    """Regression: a DETACHED_PROCESS child died with the launcher on Windows."""
    import subprocess
    calls = []
    monkeypatch.setattr(native_nats.sys, 'platform', 'win32')
    monkeypatch.setattr(subprocess, 'CREATE_NEW_CONSOLE', 0x10, raising=False)
    monkeypatch.setattr(subprocess, 'STARTF_USESHOWWINDOW', 1, raising=False)
    monkeypatch.setattr(subprocess, 'STARTUPINFO', lambda: type('S', (), {'dwFlags': 0, 'wShowWindow': 0})(), raising=False)
    monkeypatch.setattr(subprocess, 'Popen', lambda command, **kw: calls.append((command, kw)))
    native_nats.start(tmp_path, tmp_path / 'nats-server.exe')
    command, kw = calls[0]
    assert kw['creationflags'] == 0x10, 'own console window, no DETACHED_PROCESS'
    assert kw['startupinfo'].wShowWindow == 7, 'minimised'
    assert '-c' in command and str(native_nats.CONFIG.name) in command[command.index('-c') + 1]


def test_action_daemon_retries_the_bus_forever():
    source = (ROOT / 'src' / 'ultron' / 'agents' / 'action_daemon.py').read_text()
    assert 'max_reconnect_attempts=-1' in source
