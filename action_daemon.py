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
from typing import Any, Dict, List

import edge_tts
import psutil
import pygame
from nats.aio.client import Client as NATS

NATS_URL = os.getenv("NATS_URL", "nats://127.0.0.1:4222")
SUBJECT = "ultron.>"

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
        pygame.mixer.init(frequency=24000)

    async def _notify_speaking_state(self, is_speaking: bool):
        """Notifies the voice listener when Ultron is emitting sound to prevent acoustic loops."""
        if self.nc and self.nc.is_connected:
            try:
                await self.nc.publish(
                    "ultron.status.speaking",
                    json.dumps({"speaking": is_speaking}).encode(),
                )
            except Exception as e:
                logger.error(f"[ULTRON VOICE STATUS ERROR]: {e}")

    async def speak_and_wait(self, text: str):
        """Generates TTS audio and blocks synchronously until physical playback finishes."""
        if not text:
            return

        async with self._lock:
            logger.info(f'>>> [ULTRON SPEAKING]: "{text}"')
            await self._notify_speaking_state(True)

            try:
                communicate = edge_tts.Communicate(
                    text,
                    ULTRON_VOICE,
                    pitch=ULTRON_PITCH,
                    rate=ULTRON_RATE,
                )
                audio_data = bytearray()
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_data.extend(chunk["data"])

                if audio_data:
                    sound_file = io.BytesIO(audio_data)
                    pygame.mixer.music.load(sound_file)
                    pygame.mixer.music.play()

                    # Block until playback physically ends on sound card
                    while pygame.mixer.music.get_busy():
                        await asyncio.sleep(0.05)

            except Exception as e:
                logger.error(f"[ULTRON VOICE ERROR]: {e}")

            finally:
                # Buffer gap to absorb room reverberation
                await asyncio.sleep(0.3)
                await self._notify_speaking_state(False)


class ActionDaemon:

    def __init__(self, nats_url: str = NATS_URL, subject: str = SUBJECT):
        self.nats_url = nats_url
        self.subject = subject
        self.nc = NATS()
        self.voice: UltronVoiceEngine = None
        self.cooldowns: Dict[str, float] = {}
        self._shutdown_event = asyncio.Event()

        self.event_handlers = {
            "clap_detected": self._handle_clap,
            "PALM OPEN": self._handle_palm_open,
            "FIST DETECTED": self._handle_fist,
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

    async def get_diagnostics(self):
        try:
            cpu = psutil.cpu_percent(interval=0.3)
            ram = psutil.virtual_memory().percent
            battery = psutil.sensors_battery()
            power_str = (
                f"{battery.percent} percent remaining"
                if battery
                else "direct power grid"
            )

            diag_msg = (
                f"Core diagnostics verified. Processing utilization at {cpu} percent. "
                f"Memory capacity at {ram} percent. Operational on {power_str}."
            )
            logger.info(f"[DIAGNOSTICS]: {diag_msg}")
            await self.speak_and_wait(diag_msg)
        except Exception as e:
            logger.error(f"[DIAGNOSTICS ERROR]: {e}")

    async def open_application(self, app_name: str):
        if not app_name:
            return

        app_clean = app_name.lower().strip()
        app_map = {
            "task manager": "taskmgr.exe",
            "taskmanager": "taskmgr.exe",
            "chrome": "chrome.exe",
            "google chrome": "chrome.exe",
            "browser": "https://www.google.com",
            "notepad": "notepad.exe",
            "calculator": "calc.exe",
            "calc": "calc.exe",
            "cmd": "cmd.exe",
            "terminal": "wt.exe",
        }

        target = app_map.get(app_clean, app_clean)

        # Confirm verbally before process launch
        await self.speak_and_wait(f"Executing sequence. Initializing {app_name}.")

        logger.info(f"[LAUNCH]: Launching '{target}' for app '{app_name}'...")
        try:
            if target.startswith("http://") or target.startswith("https://"):
                webbrowser.open(target)
            else:
                subprocess.Popen(target, shell=True)
        except Exception as e:
            logger.error(f"[LAUNCH ERROR]: Could not launch '{app_name}': {e}")

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

    async def execute_single_action(self, action_item: Dict[str, Any]):
        """Executes a single step in the task sequence strictly to completion."""
        action_type = action_item.get("action")
        action_data = action_item

        if action_type in [
            "get_diagnostics",
            "diagnostics",
            "system_diagnostics",
        ]:
            await self.get_diagnostics()

        elif action_type in [
            "open_app",
            "launch_app",
            "open_application",
        ]:
            app_name = (
                action_data.get("app")
                or action_data.get("target")
                or action_data.get("name")
            )
            await self.open_application(app_name)

        elif action_type == "lock_pc":
            if sys.platform == "win32":
                await self.speak_and_wait("Locking workstation. Strings off.")
                ctypes.windll.user32.LockWorkStation()

        elif action_type == "custom_speech":
            speech_text = action_data.get("speech") or action_data.get("text")
            if speech_text:
                await self.speak_and_wait(speech_text)

    async def message_handler(self, msg):
        """Processes incoming messages through a strict sequential task queue."""
        try:
            payload: Dict[str, Any] = json.loads(msg.data.decode())

            # Standalone voice channel message
            if msg.subject == "ultron.voice":
                speech_text = payload.get("text") or payload.get("speech")
                if speech_text:
                    await self.speak_and_wait(speech_text)
                return

            # Construct ordered execution pipeline
            task_pipeline: List[Dict[str, Any]] = []

            # Step 1: Add intro speech if present alongside action list
            intro_speech = payload.get("speech") or payload.get("text")
            if intro_speech and "actions" in payload:
                task_pipeline.append({"action": "custom_speech", "speech": intro_speech})

            # Step 2: Add actions array or single action payload
            if "actions" in payload and isinstance(payload["actions"], list):
                for act in payload["actions"]:
                    if isinstance(act, str):
                        task_pipeline.append({"action": act})
                    elif isinstance(act, dict):
                        task_pipeline.append(act)

            elif "action" in payload:
                task_pipeline.append(payload)

            elif intro_speech:
                task_pipeline.append({"action": "custom_speech", "speech": intro_speech})

            # --- STRICT SEQUENTIAL EXECUTION LOOP ---
            for step_idx, task in enumerate(task_pipeline, start=1):
                logger.info(
                    f"[PIPELINE STEP {step_idx}/{len(task_pipeline)}]: Executing {task}"
                )
                await self.execute_single_action(task)

            # Gesture Events Handling
            event_type = payload.get("event") or payload.get("gesture")
            if event_type:
                logger.info(f"[ACTION EVENT] Event='{event_type}'")
                handler = self.event_handlers.get(event_type)
                if handler:
                    await handler()

        except json.JSONDecodeError:
            logger.error(f"[DAEMON ERROR] Invalid JSON on subject '{msg.subject}'")
        except Exception as e:
            logger.error(f"[DAEMON ERROR] Failed to process message: {e}")

    async def start(self):
        await self.nc.connect(self.nats_url)

        # Capture running asyncio loop and bind Ultron Voice Engine
        loop = asyncio.get_running_loop()
        self.voice = UltronVoiceEngine(self.nc, loop=loop)

        logger.info(
            f"[ULTRON] Action daemon online. Subscribed to '{self.subject}'..."
        )
        await self.speak_and_wait("Ultron core action daemon online.")

        await self.nc.subscribe(self.subject, cb=self.message_handler)
        await self._shutdown_event.wait()
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
