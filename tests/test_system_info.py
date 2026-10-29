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
    assert '1 day, 1 hour, 1 minute' in reply
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


def test_uptime_zero_and_missing_are_explicit():
    assert system_info.format_uptime({'uptime_seconds': 0}) == 'System uptime: less than a minute.'
    assert system_info.format_uptime({}) == 'System uptime: unavailable.'


def test_process_memory_is_sorted_bounded_and_omits_sensitive_fields(monkeypatch):
    def processes(attrs, ad_value):
        assert attrs == ['pid', 'name', 'memory_info']
        return [SimpleNamespace(info={'pid': i, 'name': 'app',
                 'memory_info': SimpleNamespace(rss=i * 100), 'cmdline': 'secret'})
                for i in range(12)] + [SimpleNamespace(info={'memory_info': None})]
    monkeypatch.setattr(system_info.psutil, 'process_iter', processes)
    result = diagnostics.collect_process_memory()
    assert len(result['top_processes']) == 10
    assert result['top_processes'][0] == {'pid': 11, 'name': 'app', 'rss_bytes': 1100}
    assert result['skipped'] == 1
    assert 'secret' not in str(result)


def test_local_clock_uses_explicit_offset_and_midnight_date():
    from datetime import datetime, timezone, timedelta
    from ultron_control.local_facts import clock_reply
    now = datetime(2026, 10, 18, 0, 5, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert '00:05 (UTC+05:30)' in clock_reply('clock', now=now)
    assert '18 October 2026' in clock_reply('date', now=now)


def test_disk_fact_is_scoped_and_does_not_leak_exception(monkeypatch):
    from ultron_control import local_facts
    gib = 1024 ** 3
    monkeypatch.setattr(local_facts.shutil, 'disk_usage', lambda path: SimpleNamespace(total=100*gib, used=80*gib, free=20*gib))
    assert local_facts.disk_reply() == 'Volume containing your home folder: 20.0 GiB free of 100.0 GiB; 80.0 GiB used. Other volumes were not checked.'
    def fail(path):
        raise PermissionError('private path')
    monkeypatch.setattr(local_facts.shutil, 'disk_usage', fail)
    assert 'unavailable' in local_facts.disk_reply()
    assert 'private path' not in local_facts.disk_reply()


def test_local_facts_do_not_consume_mixed_commands():
    from ultron_control.intent_guard import local_information_kind
    for prompt in ['What time is it and open Calculator?', 'Check disk space then delete old files.',
                   'Remind me tomorrow', 'What time is it in London?', 'What day is my appointment?']:
        assert local_information_kind(prompt) is None
    assert local_information_kind('Okay, what time is it?') == 'clock'
    assert local_information_kind('What can you do?') == 'capabilities'
