import os
import random

import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import re
import time
from typing import Optional, Tuple

from speech_runtime import SpeechConfig, load_whisper_model, transcription_options
import numpy as np
from nats.aio.client import Client as NATS
import sounddevice as sd

from visual_events import publish_visual_event


# =========================================================
# DEPLOYMENT CONFIGURATION
# =========================================================

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
        audio_queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
    ):
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

        if status:
            logging.warning(
                f"[AUDIO STREAM STATUS]: {status}"
            )

        data_copy = (
            indata
            .copy()
            .flatten()
        )

        self.loop.call_soon_threadsafe(
            self.queue.put_nowait,
            data_copy,
        )

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
    audio_queue: asyncio.Queue,
    samples: int = 25,
) -> float:

    logging.info(
        "[ULTRON EARS]: Calibrating ambient room noise... "
        "Stay quiet."
    )

    rms_values = []

    for _ in range(samples):

        block = await asyncio.wait_for(audio_queue.get(), timeout=5.0)

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
        r"\b(?:hey\s+|ok\s+|hello\s+)?ultron\b"
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

    audio_queue = asyncio.Queue()

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
    )

    try:
        stream_manager.start()
        silence_threshold = await calibrate_ambient_noise(audio_queue)
    except Exception:
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

    last_interaction_time = time.time()

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


    audio_buffer = []

    pre_roll_buffer = deque(
        maxlen=PREROLL_BLOCKS
    )

    start_speech_time = 0.0
    last_speech_time = 0.0
    last_meter_time = 0.0

    is_recording = False


    # =====================================================
    # MAIN AUDIO LOOP
    # =====================================================

    try:

        while True:

            now = time.time()


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

            block = await audio_queue.get()


            # -------------------------------------------------
            # MUTE DURING TTS
            # -------------------------------------------------

            if acoustic_gate.is_speaking:

                audio_buffer.clear()

                pre_roll_buffer.clear()

                is_recording = False

                continue


            # -------------------------------------------------
            # RMS ENERGY
            # -------------------------------------------------

            rms_energy = np.sqrt(
                np.mean(block ** 2)
            )


            # =================================================
            # SPEECH DETECTED
            # =================================================

            if rms_energy > silence_threshold:

                if not is_recording:

                    is_recording = True

                    start_speech_time = now

                    audio_buffer = list(
                        pre_roll_buffer
                    )

                    audio_buffer.append(
                        block
                    )

                    pre_roll_buffer.clear()


                    # =================================================
                    # REAL ULTRON VISUAL STATE
                    #
                    # Microphone has actually detected speech.
                    # Drive the computational entity into LISTENING.
                    #
                    # Failure of the visual bus must NEVER break
                    # the audio pipeline.
                    # =================================================

                    try:

                        await publish_visual_event(
                            nc,
                            "listening",
                            source="voice_listener",
                        )

                    except Exception as e:

                        logging.warning(
                            "[VISUAL EVENT WARNING]: "
                            "Failed to publish LISTENING state: "
                            f"{e}"
                        )


                    status_str = (
                        "SESSION ACTIVE"
                        if is_active_session
                        else "STANDBY - AWAITING WAKE WORD"
                    )

                    print(
                        f"\n[MIC ACTIVATED ({status_str}) "
                        f"- RMS: {rms_energy:.4f}]: "
                        "Listening to sentence..."
                    )

                else:

                    audio_buffer.append(
                        block
                    )


                last_speech_time = now


                # -------------------------------------------------
                # AUDIO METER
                # -------------------------------------------------

                if (
                    now - last_meter_time
                    > 0.1
                ):

                    bars = int(
                        min(
                            (
                                rms_energy
                                / silence_threshold
                            ) * 8,
                            25,
                        )
                    )

                    print(
                        f"\r[AUDIO IN]: "
                        f"{'█' * bars:<25}",
                        end="",
                        flush=True,
                    )

                    last_meter_time = now


            # =================================================
            # SILENCE AFTER SPEECH
            # =================================================

            elif is_recording:

                audio_buffer.append(
                    block
                )

                silence_duration = (
                    now - last_speech_time
                )

                total_duration = (
                    now - start_speech_time
                )


                # -------------------------------------------------
                # COMPLETE UTTERANCE
                # -------------------------------------------------

                if (
                    silence_duration
                    >= SPEECH_POST_SILENCE_SEC
                    or total_duration
                    >= MAX_AUDIO_DURATION_SEC
                ):

                    full_audio = np.concatenate(
                        audio_buffer,
                        axis=0,
                    )

                    audio_buffer.clear()

                    is_recording = False

                    print(
                        "\n[ULTRON EARS]: "
                        "Processing speech buffer..."
                    )


                    # -------------------------------------------------
                    # WHISPER
                    # -------------------------------------------------

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

                                last_interaction_time = time.time()

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
                                time.time()
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


            # =================================================
            # NO SPEECH
            # =================================================

            else:

                pre_roll_buffer.append(
                    block
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