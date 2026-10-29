#!/usr/bin/env python3
"""audio_listen.py - Crest-factor based clap detection (rejects sustained speech).
Cross-platform (Windows-safe) via KeyboardInterrupt handling."""
import asyncio, json, sys
from datetime import datetime, timezone
import numpy as np
import sounddevice as sd
from nats.aio.client import Client as NATS

NATS_URL = "nats://localhost:4222"
SUBJECT = "ultron.audio"
DEVICE_ID = "laptop_01"
SAMPLE_RATE = 16000
BLOCKSIZE = 256
DEBOUNCE_SECONDS = 1.0
PEAK_THRESHOLD = 0.03
CREST_TRIGGER = 3.8
CREST_REJECT = 3.0


def select_input_device():
    devices = sd.query_devices()
    print("[DEVICES] Available input devices:")
    for i, d in enumerate(devices):
        if d["max_input_channels"] > 0:
            print(f"  [{i}] {d['name']} (in_ch={d['max_input_channels']})")

    default_idx = sd.default.device[0]
    if default_idx is not None and default_idx >= 0:
        print(f"[DEVICE SELECTED] Using default input device: {devices[default_idx]['name']}")
        return default_idx

    for i, d in enumerate(devices):
        if d["max_input_channels"] > 0 and ("microphone" in d["name"].lower() or "realtek" in d["name"].lower()):
            print(f"[DEVICE SELECTED] Matched keyword device: {d['name']}")
            return i

    for i, d in enumerate(devices):
        if d["max_input_channels"] > 0:
            print(f"[DEVICE SELECTED] Fallback to first available: {d['name']}")
            return i

    raise RuntimeError("No input devices found.")


class ClapDetector:
    def __init__(self, loop: asyncio.AbstractEventLoop, device_idx: int):
        self.loop = loop
        self.device_idx = device_idx
        self.queue: asyncio.Queue = asyncio.Queue()
        self.nc = NATS()
        self.stream = None
        self.last_event_time = 0.0

    async def connect_nats(self):
        await self.nc.connect(servers=[NATS_URL], max_reconnect_attempts=-1,
                               reconnect_time_wait=2, allow_reconnect=True)
        print(f"[NATS] Connected to {NATS_URL}")

    def _callback(self, indata, frames, time_info, status):
        if status:
            print(f"\n[STREAM WARNING] {status}", file=sys.stderr)
        mono = indata[:, 0].copy()
        self.loop.call_soon_threadsafe(self.queue.put_nowait, mono)

    async def start_stream(self):
        self.stream = sd.InputStream(device=self.device_idx, samplerate=SAMPLE_RATE,
                                      channels=1, dtype="float32", blocksize=BLOCKSIZE,
                                      callback=self._callback)
        self.stream.start()
        print(f"[AUDIO] Stream started on device index {self.device_idx} "
              f"(blocksize={BLOCKSIZE} @ {SAMPLE_RATE}Hz)")

    async def publish_event(self, peak: float, crest: float):
        payload = {
            "device_id": DEVICE_ID, "event": "clap_detected",
            "amplitude": round(peak, 5),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.nc.publish(SUBJECT, json.dumps(payload).encode())
        print(f"[AUDIO TRIGGERED]: Clap Detected! (Peak: {peak:.4f}, Crest: {crest:.2f})")

    async def process(self):
        while True:
            block = await self.queue.get()
            peak = float(np.max(np.abs(block)))
            rms_val = float(np.sqrt(np.mean(np.square(block, dtype=np.float64))))
            crest_factor = peak / (rms_val + 1e-6)
            now = self.loop.time()

            if crest_factor < CREST_REJECT:
                continue  # sustained energy (speech/music) -> reject

            is_clap = peak > PEAK_THRESHOLD and crest_factor > CREST_TRIGGER
            if is_clap and (now - self.last_event_time) >= DEBOUNCE_SECONDS:
                self.last_event_time = now
                await self.publish_event(peak, crest_factor)

    async def shutdown(self):
        print("\n[SHUTDOWN] Cleaning up...")
        if self.stream:
            self.stream.stop()
            self.stream.close()
        if self.nc.is_connected:
            await self.nc.close()
        print("[SHUTDOWN] Complete.")


async def main():
    loop = asyncio.get_running_loop()
    device_idx = select_input_device()
    detector = ClapDetector(loop, device_idx)
    try:
        await detector.connect_nats()
        await detector.start_stream()
        await detector.process()
    finally:
        await detector.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INTERRUPT] CTRL+C received, exiting.")