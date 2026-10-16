"""Read-only, timestamped system facts shared by the brain and diagnostics."""
from datetime import datetime, timezone
import time

import psutil


def collect_telemetry():
    result = {"observed_at": datetime.now(timezone.utc).isoformat(), "errors": {}}
    probes = {
        "cpu_percent": lambda: psutil.cpu_percent(interval=0.1),
        "memory_percent": lambda: psutil.virtual_memory().percent,
        "uptime_seconds": lambda: max(0, int(time.time() - psutil.boot_time())),
    }
    for name, probe in probes.items():
        try:
            result[name] = probe()
        except Exception as exc:
            result[name] = None
            result["errors"][name] = type(exc).__name__
    try:
        battery = psutil.sensors_battery()
        result["battery_percent"] = battery.percent if battery else None
        result["power_plugged"] = battery.power_plugged if battery else None
    except Exception as exc:
        result.update(battery_percent=None, power_plugged=None)
        result["errors"]["battery"] = type(exc).__name__
    return result


def format_telemetry(data):
    parts = []
    for key, label in (("cpu_percent", "CPU"), ("memory_percent", "RAM")):
        value = data.get(key)
        parts.append(f"{label}: {value:g}%" if value is not None else f"{label}: unavailable")
    parts.append(format_uptime(data).rstrip("."))
    battery = data.get("battery_percent")
    parts.append(f"Battery: {battery:g}%" if battery is not None else "Battery reading: unavailable")
    plugged = data.get("power_plugged")
    parts.append("Power: plugged in" if plugged is True else
                 "Power: on battery" if plugged is False else "Power source: unknown")
    return "; ".join(parts) + "."


def format_uptime(data):
    seconds = data.get("uptime_seconds")
    if seconds is None:
        return "System uptime: unavailable."
    days, remaining = divmod(int(seconds), 86400)
    hours, remaining = divmod(remaining, 3600)
    units = [(days, "day"), (hours, "hour"), (remaining // 60, "minute")]
    parts = [f"{value} {unit}{'s' if value != 1 else ''}" for value, unit in units if value]
    return "System uptime: " + (", ".join(parts) if parts else "less than a minute") + "."


def format_runtime_status(data):
    connected = data.get("nats_connected")
    bus = "connected" if connected is True else "disconnected" if connected is False else "unknown"
    parts = ["My brain is responding", f"its NATS connection is {bus}"]
    if data.get("task_lookup_error"):
        parts.append("task history is unavailable")
    elif data.get("latest_task"):
        task = data["latest_task"]
        parts.append(f"latest recorded task: {task.get('status') or 'unknown'}")
        if task.get("error"):
            parts.append("recorded error: " + str(task["error"])[:240])
    else:
        parts.append("no previous task is recorded")
    return "; ".join(parts) + ". I have not run a full system health check; microphone and speaker health are unverified."
