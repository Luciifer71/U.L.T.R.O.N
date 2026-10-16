from types import SimpleNamespace

from ultron_control import system_info
import ultron_diagnostics as diagnostics


def test_uptime_and_battery_are_separate_measurements(monkeypatch):
    monkeypatch.setattr(system_info.time, 'time', lambda: 90061)
    monkeypatch.setattr(system_info.psutil, 'boot_time', lambda: 0)
    monkeypatch.setattr(system_info.psutil, 'cpu_percent', lambda **kw: 5.4)
    monkeypatch.setattr(system_info.psutil, 'virtual_memory', lambda: SimpleNamespace(percent=90))
    monkeypatch.setattr(system_info.psutil, 'sensors_battery', lambda: SimpleNamespace(percent=80, power_plugged=False))
    data = system_info.collect_telemetry()
    reply = system_info.format_telemetry(data)
    assert data['uptime_seconds'] == 90061 and data['errors'] == {}
    assert '1 days, 1 hours, 1 minutes' in reply
    assert 'Battery: 80%' in reply and 'Power: on battery' in reply


def test_missing_battery_does_not_claim_ac_power(monkeypatch):
    monkeypatch.setattr(system_info.psutil, 'sensors_battery', lambda: None)
    def unavailable():
        raise OSError('private details')
    monkeypatch.setattr(system_info.psutil, 'boot_time', unavailable)
    data = system_info.collect_telemetry()
    reply = system_info.format_telemetry(data)
    assert 'uptime: unavailable' in reply and 'Power source: unknown' in reply
    assert data['errors']['uptime_seconds'] == 'OSError'
    assert 'private' not in str(data)


def test_diagnostics_refuses_remote_or_credential_endpoints(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError('Must not make a connection')
    monkeypatch.setattr(diagnostics, 'urlopen', forbidden)
    monkeypatch.setattr(diagnostics.socket, 'create_connection', forbidden)
    assert diagnostics.check_ollama('http://example.com', 'model')['reason'] == 'ValueError'
    assert diagnostics.check_nats('nats://user:secret@localhost:4222')['reason'] == 'ValueError'


def test_model_inventory_does_not_claim_inference(monkeypatch):
    import io
    monkeypatch.setattr(diagnostics, 'urlopen', lambda *a, **kw: io.BytesIO(b'{"models":[{"name":"qwen3:8b"}]}'))
    assert diagnostics.check_ollama('http://localhost:11434', 'qwen3:8b')['status'] == 'ok'
    assert diagnostics.check_ollama('http://localhost:11434', 'missing')['status'] == 'warning'
