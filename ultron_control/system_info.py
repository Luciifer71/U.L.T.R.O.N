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
    seconds = data.get("uptime_seconds")
    if seconds is None:
        parts.append("System uptime: unavailable")
    else:
        days, remaining = divmod(int(seconds), 86400)
        hours, remaining = divmod(remaining, 3600)
        parts.append(f"System uptime: {days} days, {hours} hours, {remaining // 60} minutes")
    battery = data.get("battery_percent")
    parts.append(f"Battery: {battery:g}%" if battery is not None else "Battery reading: unavailable")
    plugged = data.get("power_plugged")
    parts.append("Power: plugged in" if plugged is True else
                 "Power: on battery" if plugged is False else "Power source: unknown")
    return "; ".join(parts) + "."
