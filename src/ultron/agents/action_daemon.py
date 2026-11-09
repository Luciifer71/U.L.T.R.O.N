import asyncio
import ctypes
import io
import json
import logging
import os
import subprocess
import sys
import time
import webbrowser
from typing import Any, Dict

import edge_tts
import pygame
from nats.aio.client import Client as NATS
from ultron.control.reply_delivery import SpeechQueue
from ultron.control.operations import OPS_PREFIX, heartbeat_loop

NATS_URL = os.getenv("NATS_URL", "nats://127.0.0.1:4222")
# The daemon speaks replies and handles the experimental gesture/clap events.
# It deliberately does not subscribe to "ultron.>": a wildcard let any bus
# message reach speech or desktop actions without the brain's checks.
VOICE_SUBJECT = "ultron.voice"
GESTURE_SUBJECT = "ultron.gestures"  # tools/experimental/gesture.py
AUDIO_EVENT_SUBJECT = "ultron.audio"  # tools/experimental/audio_listen.py
SUBJECTS = (VOICE_SUBJECT, GESTURE_SUBJECT, AUDIO_EVENT_SUBJECT)

# Voice configuration tuned for Ultron's dark, imposing tone
ULTRON_VOICE = "en-US-ChristopherNeural"
ULTRON_PITCH = "-12Hz"
ULTRON_RATE = "-2%"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("UltronDaemon")


class UltronVoiceEngine:
    """Non-blocking streaming TTS Engine with hardware-bound sequential acoustic lock."""

    def __init__(self, nats_client: NATS, loop: asyncio.AbstractEventLoop):
        self.nc = nats_client
        self.loop = loop
        self._lock = asyncio.Lock()
        self.speaking = False
        self.state_version = time.time_ns()
        pygame.mixer.init(frequency=24000)

    async def _notify_speaking_state(self, is_speaking: bool):
        """Notifies the voice listener when Ultron is emitting sound to prevent acoustic loops."""
        self.speaking = is_speaking
        self.state_version = time.time_ns()
        if self.nc and self.nc.is_connected:
            try:
                await self.nc.publish(
                    "ultron.status.speaking",
                    json.dumps({"speaking": is_speaking, "version": self.state_version}).encode(),
                )
                await asyncio.wait_for(self.nc.flush(), timeout=1)
            except Exception as e:
                logger.error(f"[ULTRON VOICE STATUS ERROR]: {e}")

    async def speak_and_wait(self, text: str):
        """Wait for mixer playback; software status cannot prove physical audibility."""
        if not text:
            return

        async with self._lock:
            logger.info(f'>>> [ULTRON SPEAKING]: "{text}"')
            try:
                await self._notify_speaking_state(True)
                communicate = edge_tts.Communicate(
                    text,
                    ULTRON_VOICE,
                    pitch=ULTRON_PITCH,
                    rate=ULTRON_RATE,
                )
                audio_data = bytearray()
                async with asyncio.timeout(20):
                    async for chunk in communicate.stream():
                        if chunk["type"] == "audio":
                            audio_data.extend(chunk["data"])
                if not audio_data:
                    raise RuntimeError('Speech synthesis returned no audio')
                logger.info('[TTS READY]: synthesized_bytes=%d', len(audio_data))
                sound_file = io.BytesIO(audio_data)
                pygame.mixer.music.load(sound_file)
                pygame.mixer.music.play()
                if not pygame.mixer.music.get_busy():
                    raise RuntimeError('Audio mixer did not start playback')
                started = time.monotonic()
                logger.info('[TTS PLAYBACK STARTED]: mixer active; physical audibility unverified')
                async with asyncio.timeout(90):
                    while pygame.mixer.music.get_busy():
                        await asyncio.sleep(0.05)
                logger.info('[TTS PLAYBACK FINISHED]: elapsed_seconds=%.3f', time.monotonic() - started)

            except TimeoutError:
                logger.error('[ULTRON VOICE ERROR]: Speech timed out; stopping playback and releasing microphone gate.')
            except Exception as e:
                logger.error(f"[ULTRON VOICE ERROR]: {e}")

            finally:
                pygame.mixer.music.stop()
                # Buffer gap to absorb room reverberation
                await asyncio.sleep(0.3)
                await self._notify_speaking_state(False)


class ActionDaemon:

    def __init__(self, nats_url: str = NATS_URL):
        self.nats_url = nats_url
        self.nc = NATS()
        self.voice: UltronVoiceEngine = None
        self.cooldowns: Dict[str, float] = {}
        self._shutdown_event = asyncio.Event()

        # Each experimental event is accepted only on the subject its tool uses.
        self.event_handlers = {
            (AUDIO_EVENT_SUBJECT, "clap_detected"): self._handle_clap,
            (GESTURE_SUBJECT, "PALM OPEN"): self._handle_palm_open,
            (GESTURE_SUBJECT, "FIST DETECTED"): self._handle_fist,
        }

    async def speak_and_wait(self, text: str):
        """Delegates voice execution to UltronVoiceEngine."""
        if not text or not self.voice:
            return
        await self.voice.speak_and_wait(text)

    def is_cooled_down(self, event_type: str, seconds: float = 3.0) -> bool:
        now = time.monotonic()
        last = self.cooldowns.get(event_type, 0.0)
        if now - last > seconds:
            self.cooldowns[event_type] = now
            return True
        return False

    async def _handle_clap(self):
        if self.is_cooled_down("clap"):
            await self.speak_and_wait("Acoustic pulse confirmed. Launching network interface.")
            webbrowser.open("https://www.google.com")

    async def _handle_palm_open(self):
        if self.is_cooled_down("palm"):
            await self.speak_and_wait("Visual signature confirmed. Opening primary workspace.")
            subprocess.Popen(["notepad.exe"])

    async def _handle_fist(self):
        if self.is_cooled_down("fist"):
            await self.speak_and_wait("Isolation protocol active. Locking workstation.")
            if sys.platform == "win32":
                ctypes.windll.user32.LockWorkStation()

    async def message_handler(self, msg):
        """Speak replies and run the fixed experimental event handlers. Nothing else."""
        if msg.subject not in SUBJECTS or msg.subject.startswith(OPS_PREFIX):
            return
        try:
            payload: Dict[str, Any] = json.loads(msg.data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.error(f"[DAEMON ERROR] Invalid JSON on subject '{msg.subject}'")
            return
        if not isinstance(payload, dict):
            return
        try:
            if msg.subject == VOICE_SUBJECT:
                speech_text = payload.get("speech") if "speech" in payload else payload.get("text")
                if speech_text and not payload.get("silent"):
                    key = payload.get("statusKey")
                    self.speech_queue.submit(speech_text, key=key if isinstance(key, str) else None,
                                             ttl=20 if key else None)
                return

            event_type = payload.get("event") if msg.subject == AUDIO_EVENT_SUBJECT else payload.get("gesture")
            handler = self.event_handlers.get((msg.subject, event_type))
            if handler:
                logger.info(f"[ACTION EVENT] Event='{event_type}'")
                await handler()
        except Exception as e:
            logger.error(f"[DAEMON ERROR] Failed to process message: {e}")

    async def start(self):
        await self.nc.connect(self.nats_url)

        # Capture running asyncio loop and bind Ultron Voice Engine
        loop = asyncio.get_running_loop()
        self.voice = UltronVoiceEngine(self.nc, loop=loop)

        self.speech_queue = SpeechQueue(self.speak_and_wait)
        speech_worker = asyncio.create_task(self.speech_queue.run())

        async def cancel_speech(msg):
            await self.speech_queue.cancel()

        async def voice_state(msg):
            if msg.reply:
                await self.nc.publish(msg.reply, json.dumps({
                    "speaking": self.voice.speaking,
                    "version": self.voice.state_version,
                }).encode())

        await self.nc.subscribe("ultron.voice.cancel", cb=cancel_speech)
        await self.nc.subscribe("ultron.voice.state", cb=voice_state)
        for subject in SUBJECTS:
            await self.nc.subscribe(subject, cb=self.message_handler)
        await self.nc.flush()
        heartbeat = asyncio.create_task(heartbeat_loop(self.nc, "action_daemon"))
        logger.info(f"[ULTRON] Action daemon online. Subscribed to {', '.join(SUBJECTS)}.")
        self.speech_queue.submit("Ultron core action daemon online.")
        try:
            await self._shutdown_event.wait()
        finally:
            heartbeat.cancel()
            speech_worker.cancel()
            try:
                await speech_worker
            except asyncio.CancelledError:
                pass
            await self.nc.close()

async def main():
    # Instantiate your actual action daemon class defined in this file
    daemon = ActionDaemon()
    try:
        await daemon.start()
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[ULTRON] Action daemon offline.")
