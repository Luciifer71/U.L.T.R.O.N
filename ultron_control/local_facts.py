"""Small read-only facts: no model, network, calendar account or scheduling."""
from datetime import datetime
from pathlib import Path
import shutil


def clock_reply(kind, *, now=None):
    now = now if now is not None else datetime.now().astimezone()
    if now.utcoffset() is None:
        raise ValueError('Clock facts require a timezone-aware datetime.')
    offset = now.strftime('%z')
    zone = f'UTC{offset[:3]}:{offset[3:]}'
    if kind == 'clock':
        return f"This computer's local time is {now:%H:%M} ({zone})."
    if kind == 'date':
        return f"This computer's local date is {now:%A, %d %B %Y} ({zone})."
    raise ValueError('Unsupported clock fact.')


def disk_reply():
    # Scope is the volume containing the current user's home; no scan, file
    # listing or model-provided path, and no claim about other disks.
    try:
        usage = shutil.disk_usage(Path.home())
        gib = 1024 ** 3
        return (f'Volume containing your home folder: {usage.free / gib:.1f} GiB free '
                f'of {usage.total / gib:.1f} GiB; {usage.used / gib:.1f} GiB used. '
                'Other volumes were not checked.')
    except OSError:
        return 'Disk space is unavailable for the volume containing your home folder. Other volumes were not checked.'


def capabilities_reply():
    return (
        'I can open named applications, search supported websites, report system usage and uptime, '
        'and find supported files in a named user folder. For example: play Supergirl from Downloads. '
        'I can offer numbered file choices and run up to five explicit app/file steps separated by then. '
        'I can also report local time, date and home-volume disk space. '
        'Availability depends on this computer and its configuration. '
        'Email access, iPhone calls, smart-home control and scheduled reminders are not connected.'
    )
