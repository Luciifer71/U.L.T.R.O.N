"""Microphone policy and fresh-device probing without interrupting live capture.

PortAudio caches devices. A short-lived helper enumerates a fresh inventory;
only a changed inventory or a failed stream causes the listener to reopen it.
No system audio settings are changed.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys


def inventory(sd):
    apis = sd.query_hostapis()
    devices = []
    for index, item in enumerate(sd.query_devices()):
        if item['max_input_channels'] > 0:
            devices.append({'index': index, 'name': item['name'],
                            'api': apis[item['hostapi']]['name']})
    return devices


def fingerprint(devices):
    # Include indices: an identical name can acquire a different device index.
    return tuple(sorted((d['index'], d['name'], d['api']) for d in devices))


def microphone_candidates(devices):
    """Prefer headset input, then laptop array, then other physical microphones.

    Output-only headphones are absent from inventory, so the laptop mic stays.
    Name classification is a heuristic, not a claim to detect whether worn.
    """
    ranked = []
    for device in devices:
        name = device['name'].casefold()
        if any(word in name for word in ('stereo mix', 'what u hear', 'loopback',
                                         'virtual', 'cable output', 'sound mapper',
                                         'primary sound capture')):
            continue
        headset = any(word in name for word in ('headset', 'hands-free', 'hands free',
                                                'airpods', 'earbuds', 'earphone', 'headphone'))
        internal = any(word in name for word in ('microphone array', 'mic array',
                                                 'internal mic', 'built-in mic'))
        # WASAPI provides full device names; MME remains a compatibility fallback.
        api = device['api'].casefold()
        rank = (0 if headset else 1 if internal else 2 if 'mic' in name else 3,
                0 if 'wasapi' in api else 1 if api == 'mme' else 2,
                name, device['index'])
        ranked.append((rank, device))
    return [d for _, d in sorted(ranked)]


async def probe_inventory(timeout=5):
    """Fresh PortAudio enumeration, bounded and cleaned up even on cancellation."""
    process = await asyncio.create_subprocess_exec(
        sys.executable, str(Path(__file__).resolve()), '--probe',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        **({'creationflags': 0x08000000} if sys.platform == 'win32' else {}),
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
        if process.returncode:
            raise RuntimeError('Microphone inventory probe failed')
        result = json.loads(stdout)
        if not isinstance(result, list):
            raise ValueError('Invalid microphone inventory')
        fingerprint(result)  # Validate required fields before comparing.
        return result
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


if __name__ == '__main__':
    import sounddevice
    print(json.dumps(inventory(sounddevice)))
