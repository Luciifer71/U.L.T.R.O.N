import asyncio
import sys
from types import SimpleNamespace

import pytest

from microphone_runtime import fingerprint, inventory, microphone_candidates, probe_inventory


def device(index, name, api='Windows WASAPI'):
    return {'index': index, 'name': name, 'api': api}


def test_connected_headset_preferred_and_unplug_returns_to_laptop():
    laptop = device(1, 'Microphone Array (Intel Smart Sound)')
    headset = device(2, 'Headset Microphone (USB)')
    webcam = device(3, 'Microphone (Webcam)')
    assert microphone_candidates([webcam, laptop, headset])[0] == headset
    assert microphone_candidates([webcam, laptop])[0] == laptop


def test_output_only_headphones_do_not_replace_laptop_microphone():
    sd = SimpleNamespace(query_hostapis=lambda: [{'name': 'Windows WASAPI'}],
        query_devices=lambda: [dict(name='Microphone Array', max_input_channels=2, hostapi=0),
                               dict(name='Headphones', max_input_channels=0, hostapi=0)])
    assert microphone_candidates(inventory(sd)) == [device(0, 'Microphone Array')]


def test_virtual_loopbacks_are_not_automatically_selected():
    assert microphone_candidates([device(1, 'Stereo Mix'), device(2, 'Virtual Microphone'),
                                  device(3, 'CABLE Output'), device(4, 'Primary Sound Capture Driver')]) == []


def test_duplicate_backend_names_prefer_wasapi_and_inventory_ignores_order():
    mme = device(0, 'Microphone Array', 'MME')
    wasapi = device(4, 'Microphone Array')
    assert microphone_candidates([mme, wasapi]) == [wasapi, mme]
    assert fingerprint([mme, wasapi]) == fingerprint([wasapi, mme])
    assert fingerprint([wasapi]) != fingerprint([device(5, 'Microphone Array')])


@pytest.mark.parametrize('cancel', [False, True])
def test_probe_timeout_or_cancellation_kills_helper(monkeypatch, cancel):
    async def run():
        started = asyncio.Event()
        class Process:
            returncode = None
            killed = False
            async def communicate(self):
                started.set()
                await asyncio.Event().wait()
            def kill(self): self.killed = True
            async def wait(self): self.returncode = -1
        process = Process()
        async def spawn(*args, **kwargs):
            assert args[0] == sys.executable and args[-1] == '--probe'
            return process
        monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
        task = asyncio.create_task(probe_inventory(timeout=0.01))
        await started.wait()
        if cancel: task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else asyncio.TimeoutError):
            await task
        assert process.killed and process.returncode == -1
    asyncio.run(run())
