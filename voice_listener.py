import os
import random

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional, Tuple

from dotenv import load_dotenv

from speech_runtime import SpeechConfig, load_whisper_model, transcription_options
import numpy as np
from nats.aio.client import Client as NATS
import sounddevice as sd

from visual_events import publish_visual_event
from audio_pipeline import AudioFrame, AudioMailbox, UtteranceSegmenter


# =========================================================
# DEPLOYMENT CONFIGURATION
# =========================================================

# Resolve against this script, so launching from another directory is safe.
# Explicit process settings remain available for temporary test overrides.
load_dotenv(Path(__file__).resolve().with_name(".env"), override=False)
NATS_URL = os.getenv("NATS_URL", "nats://127.0.0.1:4222")
MIC_DEVICE = os.getenv("AUDIO_INPUT_DEVICE") or None
if MIC_DEVICE is not None and MIC_DEVICE.isdecimal():
    MIC_DEVICE = int(MIC_DEVICE)
SAMPLE_RATE = 16000
CHANNELS = 1
AUDIO_BLOCK_SIZE = 1024


# =========================================================
# SPEECH / VAD TIMINGS
# =========================================================

SPEECH_POST_SILENCE_SEC = 1.4
MAX_AUDIO_DURATION_SEC = 15.0
SESSION_TIMEOUT_SEC = 25.0
PREROLL_BLOCKS = 8
POST_TTS_BUFFER_PADDING = 0.6
MAX_AUDIO_BACKLOG_SEC = 2.0
AUDIO_MAILBOX_BLOCKS = max(1, int(MAX_AUDIO_BACKLOG_SEC * SAMPLE_RATE / AUDIO_BLOCK_SIZE))


# =========================================================
# ULTRON DIALOGUE
# =========================================================

ULTRON_GREETINGS = [
    "I am listening.",
    "State your request.",
    "I hear you.",
    "Proceed.",
    "Speak.",
]


# =========================================================
# WHISPER HALLUCINATION FILTER
# =========================================================

HALLUCINATION_PATTERNS = [
    r"^\s*thank you for watching\.?\s*$",
    r"^\s*subtitles by\.?\s*$",
    r"amara\.org",
    r"subscribe to",
    r"^\s*bye-bye\.?\s*$",
    r"^\s*you\.?\s*$",
    r"^\s*a\.?\s*$",
    r"^\s*the\.?\s*$",
    r"^\s*thanks for watching\.?\s*$",
    r"^\s*\[.*\]\s*$",
    r"^\s*\(.*\)\s*$",
]




logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


# =========================================================
# ACOUSTIC GATE
# =========================================================

class AcousticGate:
    """
    Hardware-bound acoustic gate suppressing microphone input
    while ULTRON is speaking.
    """

    def __init__(self):
        self._is_speaking = False
        self._lock = asyncio.Lock()

    async def set_speaking(self, status: bool):
        async with self._lock:
            self._is_speaking = status

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking


# =========================================================
# WHISPER ENGINE
# =========================================================

class WhisperEngine:

    def __init__(self, config: Optional[SpeechConfig] = None):
        self.config = config or SpeechConfig.from_env()
        self.model, self.device, self.runtime_report = load_whisper_model(self.config)

    def transcribe(
        self,
        audio_data: np.ndarray,
    ) -> Optional[str]:

        if self.model is None or len(audio_data) == 0:
            return None

        try:

            segments, _ = self.model.transcribe(
                audio_data,
                **transcription_options(self.config),
            )

            full_text = " ".join(
                segment.text.strip()
                for segment in segments
            ).strip()

            if not full_text or len(full_text) < 2:
                return None

            for pattern in HALLUCINATION_PATTERNS:

                if re.search(
                    pattern,
                    full_text,
                    re.IGNORECASE,
                ):
                    logging.info(
                        "[WHISPER FILTER]: Suppressed "
                        f"hallucinated output: '{full_text}'"
                    )

                    return None

            return full_text

        except Exception as e:

            logging.error(
                f"[WHISPER ERROR]: Inference failed: {e}"
            )

            return None


# =========================================================
# RESILIENT AUDIO STREAM
# =========================================================

class ResilientAudioStream:

    def __init__(
        self,
        audio_queue: AudioMailbox,
        loop: asyncio.AbstractEventLoop,
        acoustic_gate: Optional[AcousticGate] = None,
    ):
        self.gate = acoustic_gate
        self._sequence = 0
        self.queue = audio_queue
        self.loop = loop
        self.stream: Optional[sd.InputStream] = None

    def _audio_callback(
        self,
        indata,
        frames,
        time_info,
        status,
    ):

        self._sequence += 1
        frame = AudioFrame(
            samples=indata.copy().flatten(),
            captured_at=time.monotonic(),
            sequence=self._sequence,
            muted=bool(self.gate and self.gate.is_speaking),
            discontinuity=bool(status),
        )
        self.queue.push(frame)

    def start(self):

        try:

            sd.check_input_settings(
                device=MIC_DEVICE, samplerate=SAMPLE_RATE,
                channels=CHANNELS, dtype="float32",
            )
            device_info = sd.query_devices(
                device=MIC_DEVICE, kind="input"
            )

            device_name = device_info.get(
                "name",
                "Default Mic",
            )

            logging.info(
                "[AUDIO ENGINE]: Attached to Device -> "
                f"'{device_name}'"
            )

            self.stream = sd.InputStream(
                device=MIC_DEVICE,
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                blocksize=AUDIO_BLOCK_SIZE,
                callback=self._audio_callback,
            )

            self.stream.start()

            logging.info(
                "[AUDIO ENGINE]: SoundDevice microphone "
                "stream active."
            )

        except Exception as e:

            logging.error(
                f"[AUDIO HARDWARE ERROR]: {e}"
            )
            if self.stream is not None:
                self.stream.close()
                self.stream = None
            raise RuntimeError("Microphone startup failed; run speech_diagnostics.py --list-mics") from e


# =========================================================
# AMBIENT NOISE CALIBRATION
# =========================================================

async def calibrate_ambient_noise(
    audio_queue: AudioMailbox,
    samples: int = 25,
) -> float:

    logging.info(
        "[ULTRON EARS]: Calibrating ambient room noise... "
        "Stay quiet."
    )

    rms_values = []
    deadline = time.monotonic() + 10.0
    while len(rms_values) < samples:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("No clean microphone audio available during calibration")
        block = await asyncio.wait_for(audio_queue.get(), timeout=min(5.0, remaining))

        if isinstance(block, AudioFrame):
            if block.muted or block.discontinuity or time.monotonic() - block.captured_at > MAX_AUDIO_BACKLOG_SEC:
                continue
            block = block.samples

        rms = float(
            np.sqrt(
                np.mean(block ** 2)
            )
        )

        rms_values.append(rms)

    baseline_rms = float(
        np.percentile(
            rms_values,
            75,
        )
    )

    dynamic_threshold = max(
        baseline_rms * 2.0,
        baseline_rms + 0.004,
        0.008,
    )

    logging.info(
        "[CALIBRATION COMPLETE]: "
        f"Baseline RMS: {baseline_rms:.4f} | "
        f"Threshold: {dynamic_threshold:.4f}\n"
    )

    return dynamic_threshold


# =========================================================
# WAKE WORD
# =========================================================

def extract_wake_word_command(
    text: str,
) -> Tuple[bool, str]:

    pattern = (
        r"^\s*(?:(?:(?:ok(?:ay)?[\s,]+)?(?:so[\s,]+)?(?:hey|hello)[\s,]+)|ok(?:ay)?[\s,]+)?ultron\b"
    )

    match = re.search(
        pattern,
        text,
        re.IGNORECASE,
    )

    if match:

        wake_end = match.end()

        command = text[
            wake_end:
        ].strip()

        command = re.sub(
            r"^[,\.\?\!\s]+",
            "",
            command,
        )

        return True, command

    return False, ""


# =========================================================
# COMMAND VALIDATION
# =========================================================

def is_valid_command_prompt(
    prompt: str,
) -> bool:

    """
    Filters out fragments, punctuation,
    and obvious noise words.
    """

    cleaned = re.sub(
        r"[^\w\s]",
        "",
        prompt,
    ).strip().lower()

    if len(cleaned) < 3:
        return False

    if cleaned in [
        "the",
        "a",
        "an",
        "uh",
        "um",
        "ah",
        "you",
        "so",
        "oh",
    ]:
        return False

    return True


# =========================================================
# MAIN
# =========================================================

async def main():

    nc = NATS()

    try:

        await nc.connect(
            NATS_URL,
            max_reconnect_attempts=-1,
            reconnect_time_wait=2,
        )

        logging.info(
            "[ULTRON EARS ONLINE]: "
            "NATS Mesh Connected."
        )

    except Exception as e:

        logging.error(
            "[NATS ERROR]: "
            f"Connection failed ({e}). "
            "Ensure NATS server is running."
        )

        return

    acoustic_gate = AcousticGate()

    try:
        # CUDA probing/model loading must not block the NATS event loop.
        whisper_engine = await asyncio.to_thread(WhisperEngine)
    except Exception:
        await nc.close()
        raise

    loop = asyncio.get_running_loop()

    audio_queue = AudioMailbox(loop, capacity=AUDIO_MAILBOX_BLOCKS)

    thread_pool = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="whisper_worker",
    )


    # =====================================================
    # TTS SPEAKING STATE
    # =====================================================

    async def status_speaking_handler(msg):

        try:

            data = json.loads(
                msg.data.decode()
            )

            speaking_state = data.get(
                "speaking",
                False,
            )

            if speaking_state:

                await acoustic_gate.set_speaking(
                    True
                )

            else:

                await asyncio.sleep(
                    POST_TTS_BUFFER_PADDING
                )

                await acoustic_gate.set_speaking(
                    False
                )

        except Exception as e:

            logging.error(
                f"[STATUS EVENT ERROR]: {e}"
            )


    await nc.subscribe(
        "ultron.status.speaking",
        cb=status_speaking_handler,
    )


    # =====================================================
    # AUDIO ENGINE
    # =====================================================

    stream_manager = ResilientAudioStream(
        audio_queue,
        loop,
        acoustic_gate,
    )

    try:
        stream_manager.start()
        silence_threshold = await calibrate_ambient_noise(audio_queue)
    except Exception:
        audio_queue.close()
        if stream_manager.stream is not None:
            stream_manager.stream.stop()
            stream_manager.stream.close()
        thread_pool.shutdown(wait=False, cancel_futures=True)
        await nc.close()
        raise


    # =====================================================
    # SESSION STATE
    # =====================================================

    is_active_session = False

    last_interaction_time = time.monotonic()

    logging.info(
        "=================================================="
    )

    logging.info(
        "[STANDBY MODE]: "
        "Listening for 'Hey Ultron'..."
    )

    logging.info(
        "==================================================\n"
    )


    segmenter = UtteranceSegmenter(
        sample_rate=SAMPLE_RATE,
        silence_seconds=SPEECH_POST_SILENCE_SEC,
        max_seconds=MAX_AUDIO_DURATION_SEC,
        preroll_blocks=PREROLL_BLOCKS,
        max_backlog_seconds=MAX_AUDIO_BACKLOG_SEC,
    )
    last_meter_time = 0.0


    # =====================================================
    # MAIN AUDIO LOOP
    # =====================================================

    try:

        while True:

            now = time.monotonic()


            # -------------------------------------------------
            # SESSION TIMEOUT
            # -------------------------------------------------

            if is_active_session:

                if acoustic_gate.is_speaking:

                    last_interaction_time = now

                elif (
                    now - last_interaction_time
                    >= SESSION_TIMEOUT_SEC
                ):

                    is_active_session = False

                    print(
                        "\n" + "=" * 60
                    )

                    print(
                        "[SESSION TIMEOUT]: "
                        f"Inactive for "
                        f"{SESSION_TIMEOUT_SEC:.0f}s. "
                        "Returning to STANDBY."
                    )

                    print(
                        "Say 'Hey Ultron' to awaken the core."
                    )

                    print(
                        "=" * 60 + "\n"
                    )


            # -------------------------------------------------
            # GET AUDIO BLOCK
            # -------------------------------------------------

            try:
                frame = await asyncio.wait_for(audio_queue.get(), timeout=5.0)
            except asyncio.TimeoutError as e:
                raise RuntimeError("Microphone stopped delivering audio frames") from e
            now = time.monotonic()
            block = frame.samples
            rms_energy = float(np.sqrt(np.mean(block ** 2)))
            segment = segmenter.feed(
                frame, speech=rms_energy > silence_threshold,
                now=now, muted=acoustic_gate.is_speaking,
            )
            if segment.discarded_reason:
                logging.warning(
                    "[AUDIO DISCARD]: %s; repeat the complete command. Dropped frames=%s",
                    segment.discarded_reason, audio_queue.dropped_frames,
                )
                if is_active_session:
                    await nc.publish("ultron.voice", json.dumps({
                        "speech": "I lost part of that recording. Please repeat the complete command."
                    }).encode())
            if segment.started:
                try:
                    await publish_visual_event(nc, "listening", source="voice_listener")
                except Exception as e:
                    logging.warning("[VISUAL EVENT WARNING]: Failed to publish LISTENING: %s", e)
                status_str = "SESSION ACTIVE" if is_active_session else "STANDBY - AWAITING WAKE WORD"
                print(f"\n[MIC ACTIVATED ({status_str}) - RMS: {rms_energy:.4f}]: Listening to sentence...")
            if segmenter.recording and rms_energy > silence_threshold and now - last_meter_time > 0.1:
                bars = int(min((rms_energy / silence_threshold) * 8, 25))
                print(f"\r[AUDIO IN]: {'█' * bars:<25}", end="", flush=True)
                last_meter_time = now
            if segment.blocks is not None:
                full_audio = np.concatenate(segment.blocks, axis=0)
                print("\n[ULTRON EARS]: Processing speech buffer...")

                transcription = (
                    await loop.run_in_executor(
                        thread_pool,
                        whisper_engine.transcribe,
                        full_audio,
                    )
                )


                if transcription:

                    print(
                        f"[TRANSCRIPTION]: "
                        f"'{transcription}'"
                    )


                    # =============================================
                    # STANDBY SESSION
                    # =============================================

                    if not is_active_session:

                        (
                            has_wake_word,
                            remaining_command,
                        ) = extract_wake_word_command(
                            transcription
                        )


                        if has_wake_word:

                            is_active_session = True

                            last_interaction_time = time.monotonic()

                            print(
                                "\n>>> "
                                "[WAKE WORD DETECTED]: "
                                "Session Activated! "
                                "<<<"
                            )


                            greeting_text = random.choice(
                                ULTRON_GREETINGS
                            )

                            await nc.publish(
                                "ultron.voice",
                                json.dumps(
                                    {
                                        "speech": greeting_text
                                    }
                                ).encode(),
                            )

                            await nc.flush()


                            if (
                                remaining_command
                                and is_valid_command_prompt(
                                    remaining_command
                                )
                            ):

                                print(
                                    "[EXECUTING COMMAND]: "
                                    f"'{remaining_command}'"
                                )

                                payload = json.dumps(
                                    {
                                        "prompt":
                                            remaining_command
                                    }
                                ).encode()

                                await nc.publish(
                                    "ultron.intent",
                                    payload,
                                )

                                await nc.flush()

                            else:

                                print(
                                    "[SESSION READY]: "
                                    "Awaiting next instruction..."
                                )

                        else:

                            print(
                                "[IGNORED]: "
                                "Wake word 'Ultron' "
                                "not present."
                            )


                    # =============================================
                    # ACTIVE SESSION
                    # =============================================

                    else:

                        last_interaction_time = (
                            time.monotonic()
                        )

                        (
                            has_wake_word,
                            remaining_command,
                        ) = extract_wake_word_command(
                            transcription
                        )


                        if (
                            has_wake_word
                            and not remaining_command
                        ):

                            greeting_text = random.choice(
                                ULTRON_GREETINGS
                            )

                            await nc.publish(
                                "ultron.voice",
                                json.dumps(
                                    {
                                        "speech":
                                            greeting_text
                                    }
                                ).encode(),
                            )

                            await nc.flush()

                        else:

                            final_prompt = (
                                remaining_command
                                if (
                                    has_wake_word
                                    and remaining_command
                                )
                                else transcription
                            )


                            if is_valid_command_prompt(
                                final_prompt
                            ):

                                print(
                                    "[SESSION COMMAND EXECUTED]: "
                                    f"'{final_prompt}'"
                                )

                                payload = json.dumps(
                                    {
                                        "prompt":
                                            final_prompt
                                    }
                                ).encode()

                                await nc.publish(
                                    "ultron.intent",
                                    payload,
                                )

                                await nc.flush()

                            else:

                                print(
                                    "[DISCARDED NOISE PROMPT]: "
                                    f"'{final_prompt}'"
                                )


                else:

                    print(
                        "[DISCARDED]: "
                        "Audio rejected as ambient noise "
                        "or hallucination."
                    )


            await asyncio.sleep(
                0.001
            )


    # =========================================================
    # SHUTDOWN
    # =========================================================

    except (
        asyncio.CancelledError,
        KeyboardInterrupt,
    ):

        pass

    except Exception as e:

        logging.critical(
            "[SYSTEM UNHANDLED ERROR]: "
            f"{e}",
            exc_info=True,
        )

    finally:

        print(
            "\n[ULTRON EARS]: "
            "Shutting down audio systems..."
        )


        audio_queue.close()

        if stream_manager.stream:

            try:

                stream_manager.stream.stop()

                stream_manager.stream.close()

            except Exception:

                pass


        thread_pool.shutdown(
            wait=False,
            cancel_futures=True,
        )


        if nc.is_connected:

            try:

                await nc.drain()

            except Exception:

                pass

            try:

                await nc.close()

            except Exception:

                pass


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "\n[ULTRON] "
            "Process terminated."
        )
