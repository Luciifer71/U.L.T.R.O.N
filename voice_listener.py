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

from microphone_runtime import inventory, fingerprint, microphone_candidates, probe_inventory
from speech_activity import create_speech_activity
from visual_events import publish_visual_event
from audio_pipeline import AudioFrame, AudioMailbox, UtteranceSegmenter, TranscriptionWorker


# =========================================================
# DEPLOYMENT CONFIGURATION
# =========================================================

# Resolve against this script, so launching from another directory is safe.
# Explicit process settings remain available for temporary test overrides.
load_dotenv(Path(__file__).resolve().with_name(".env"), override=False)
NATS_URL = os.getenv("NATS_URL", "nats://127.0.0.1:4222")
INPUT_MODE = os.getenv("AUDIO_INPUT_MODE", "auto").strip().lower()
if INPUT_MODE not in {"auto", "pinned"}:
    raise ValueError("AUDIO_INPUT_MODE must be auto or pinned")
CONFIGURED_MIC_DEVICE = os.getenv("AUDIO_INPUT_DEVICE") or None
MIC_DEVICE = CONFIGURED_MIC_DEVICE if INPUT_MODE == "pinned" else None
if INPUT_MODE == "pinned" and MIC_DEVICE is None:
    raise ValueError("Pinned input mode requires AUDIO_INPUT_DEVICE")
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
        self._is_speaking = True
        self._version = -1
        self._lock = asyncio.Lock()

    async def set_speaking(self, status: bool, version=None):
        async with self._lock:
            if version is not None and version < self._version:
                return
            if version is not None:
                self._version = version
            changed = self._is_speaking != status
            self._is_speaking = status
            if changed:
                logging.info("[MIC STATE]: %s", "PAUSED: speaker active or state unavailable" if status else "LISTENING: microphone processing resumed")

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

        self.last_rejection = None
        if self.model is None or len(audio_data) == 0:
            return None

        try:

            segments, _ = self.model.transcribe(
                audio_data,
                **transcription_options(self.config),
            )

            segments = list(segments)
            # Decoder fallback thresholds are not an execution-confidence gate.
            # Reject the whole utterance if any speech segment is unreliable;
            # dropping only that segment could silently change a command target.
            for segment in segments:
                if (getattr(segment, 'avg_logprob', 0.0) < -1.0
                        or getattr(segment, 'compression_ratio', 0.0) > 2.4):
                    self.last_rejection = 'uncertain speech; please repeat the complete request'
                    logging.info('[WHISPER FILTER]: Uncertain segment; entire utterance rejected.')
                    return None
            full_text = " ".join(segment.text.strip() for segment in segments).strip()

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
        self.device_name = "unavailable"
        self.device_signature = None
        self.generation = 0
        self._first_frame = False

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
            discontinuity=bool(status) or self._first_frame,
            discontinuity_reason=("microphone restarted; repeat the complete request" if self._first_frame
                                  else f"audio driver: {status}" if status else None),
        )
        self._first_frame = False
        self.queue.push(frame)

    def close(self):
        stream, self.stream = self.stream, None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()

    def start(self, refresh=False):
        if refresh:
            self.close()
            # No other PortAudio streams exist in the listener process.
            sd._terminate()
            sd._initialize()
        candidates = []
        devices = None
        try:
            devices = inventory(sd)
            self.device_signature = fingerprint(devices)
            if MIC_DEVICE is None:
                candidates = microphone_candidates(devices)
        except (AttributeError, TypeError):
            # Minimal backends/test doubles can still expose a default input.
            pass
        if MIC_DEVICE is not None:
            candidates = [{'index': MIC_DEVICE, 'api': '', 'name': str(MIC_DEVICE)}]
        elif not candidates:
            if devices is not None:
                raise RuntimeError('Microphone startup failed: no physical input is available')
            candidates = [{'index': None, 'api': '', 'name': 'Windows/default input'}]
        errors = []
        for candidate in candidates:
            device = candidate['index']
            extra = {}
            try:
                if 'wasapi' in candidate['api'].casefold() and hasattr(sd, 'WasapiSettings'):
                    extra['extra_settings'] = sd.WasapiSettings(auto_convert=True)
                sd.check_input_settings(device=device, samplerate=SAMPLE_RATE,
                                        channels=CHANNELS, dtype='float32', **extra)
                info = sd.query_devices(device=device, kind='input')
                self.stream = sd.InputStream(
                    device=device, samplerate=SAMPLE_RATE, channels=CHANNELS,
                    dtype='float32', blocksize=AUDIO_BLOCK_SIZE,
                    callback=self._audio_callback, **extra)
                self._first_frame = refresh
                self.stream.start()
                self.device_name = info.get('name', candidate['name'])
                self.generation += 1
                logging.info('[AUDIO ENGINE]: Attached to Device -> %r (%s; %s)',
                             self.device_name, candidate['api'],
                             'explicit override' if MIC_DEVICE is not None else 'automatic headset/laptop selection')
                logging.info('[AUDIO ENGINE]: SoundDevice microphone stream active.')
                return
            except Exception as exc:
                errors.append(f"{candidate['name']}: {exc}")
                if self.stream is not None:
                    try:
                        self.close()
                    except Exception:
                        self.stream = None
        raise RuntimeError('Microphone startup failed: ' + '; '.join(errors))


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

    # A small acknowledgement before a direct address is supported. Do not
    # search arbitrary prose for Ultron: quoted/reported commands must not wake.
    command = re.sub(r"^\s*(?:very good|thank you|thanks|alright)[.!?,]+\s*(?=(?:hey|hello)\s+ultron\b)",
                     "", text, flags=re.IGNORECASE)
    found = False
    while True:
        match = re.search(pattern, command, re.IGNORECASE)
        if not match:
            break
        found = True
        command = re.sub(r"^[,\.\?\!\s]+", "", command[match.end():])
    return (True, command) if found else (False, "")


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

    speech_activity = await asyncio.to_thread(create_speech_activity)
    logging.info('[MIC CONFIG]: mode=%s; legacy device override %s', INPUT_MODE,
                 'ignored in automatic mode' if INPUT_MODE == 'auto' and CONFIGURED_MIC_DEVICE else 'not overridden')
    loop = asyncio.get_running_loop()

    audio_queue = AudioMailbox(loop, capacity=AUDIO_MAILBOX_BLOCKS)

    thread_pool = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="whisper_worker",
    )


    # =====================================================
    # TTS SPEAKING STATE
    # =====================================================

    async def apply_speaking(data):
        state = data.get("speaking", True)
        version = data.get("version")
        if not state:
            await asyncio.sleep(POST_TTS_BUFFER_PADDING)
        await acoustic_gate.set_speaking(bool(state), version)

    async def status_speaking_handler(msg):
        try:
            await apply_speaking(json.loads(msg.data.decode()))
        except Exception:
            await acoustic_gate.set_speaking(True)

    await nc.subscribe("ultron.status.speaking", cb=status_speaking_handler)

    async def refresh_speaking():
        try:
            state = await nc.request("ultron.voice.state", b"{}", timeout=1)
            await apply_speaking(json.loads(state.data.decode()))
        except Exception:
            # Fail muted if the speaker state is unknown; do not transcribe our TTS.
            await acoustic_gate.set_speaking(True)

    await refresh_speaking()

    async def monitor_speaker():
        while True:
            await asyncio.sleep(1)
            await refresh_speaking()

    speaker_monitor = asyncio.create_task(monitor_speaker())

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
        speaker_monitor.cancel()
        await asyncio.gather(speaker_monitor, return_exceptions=True)
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
    pending_device_change = False

    async def monitor_devices():
        nonlocal pending_device_change
        if MIC_DEVICE is not None or stream_manager.device_signature is None:
            return
        while True:
            await asyncio.sleep(10)
            try:
                current = await probe_inventory()
                pending_device_change = fingerprint(current) != stream_manager.device_signature
            except Exception as exc:
                logging.warning('[MIC DEVICE CHECK]: %s; retaining current microphone', exc)

    device_monitor = asyncio.create_task(monitor_devices())
    last_health_log = time.monotonic()
    peak_rms = 0.0
    recovery_after = 0.0

    async def recover_microphone(reason):
        nonlocal pending_device_change, silence_threshold, recovery_after, is_active_session
        logging.warning('[MIC RECOVERY]: %s; incomplete audio discarded', reason)
        # Neither pending nor in-flight transcripts from the old stream may act.
        transcriber.generation += 1
        segmenter._reject('microphone changed')
        if speech_activity is not None:
            speech_activity.reset()
        is_active_session = False
        try:
            stream_manager.start(refresh=True)
            pending_device_change = False
            # Old queued frames are stale. Calibration excludes damaged/muted data.
            audio_queue.clear()
            silence_threshold = await calibrate_ambient_noise(audio_queue)
            logging.info("[MIC READY]: Say 'Hey Ultron'. Device=%r", stream_manager.device_name)
        except Exception as exc:
            logging.error('[MIC RECOVERY]: %s; retrying automatically in 5 seconds', exc)
            pending_device_change = True
            try:
                stream_manager.close()
            except Exception:
                logging.exception('[MIC RECOVERY]: Failed to close unavailable stream')
        recovery_after = time.monotonic() + 5



    # =====================================================
    # MAIN AUDIO LOOP
    # =====================================================


    async def report_transcription_discard(reason):
        logging.warning("[STT DISCARD]: %s; repeat the complete command.", reason)
        if is_active_session:
            await nc.publish("ultron.voice", json.dumps({
                "speech": ("I could not hear that clearly. Please repeat the complete command."
                           if reason.startswith("uncertain speech") else
                           "Speech processing fell behind. Please repeat the complete command.")
            }).encode())

    async def handle_transcription(transcription, elapsed):
        nonlocal is_active_session, last_interaction_time
        logging.info("[STT]: inference_seconds=%.3f usable_transcript=%s", elapsed, bool(transcription))
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
                        "No supported direct wake address at the start of the request."
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
                            "[SESSION COMMAND DISPATCHED]: "
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
            rejection = getattr(whisper_engine, 'last_rejection', None)
            if rejection:
                await report_transcription_discard(rejection)
            print(
                "[DISCARDED]: "
                "No usable transcript (no speech, filter rejection or inference error)."
            )


    transcriber = TranscriptionWorker(
        whisper_engine.transcribe, handle_transcription, report_transcription_discard,
        executor=thread_pool,
    )
    transcription_task = asyncio.create_task(transcriber.run(), name="ultron-transcription")

    try:

        while True:

            if transcription_task.done():
                transcription_task.result()
            now = time.monotonic()


            # -------------------------------------------------
            # SESSION TIMEOUT
            # -------------------------------------------------

            if is_active_session:

                if acoustic_gate.is_speaking or transcriber.busy:

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

            if pending_device_change and now >= recovery_after:
                await recover_microphone('input device inventory changed')
                continue
            try:
                frame = await asyncio.wait_for(audio_queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                if time.monotonic() >= recovery_after:
                    await recover_microphone('no audio frames for 5 seconds')
                continue
            now = time.monotonic()
            block = frame.samples
            rms_energy = float(np.sqrt(np.mean(block ** 2)))
            peak_rms = max(peak_rms, rms_energy)
            if now - last_health_log >= 10:
                logging.info('[MIC HEALTH]: device=%r peak_rms=%.4f threshold=%.4f gate=%s mode=%s endpoint=%s',
                             stream_manager.device_name, peak_rms, silence_threshold,
                             'paused' if acoustic_gate.is_speaking else 'listening',
                             'active' if is_active_session else 'standby',
                             'silero' if speech_activity is not None else 'rms')
                peak_rms = 0.0
                last_health_log = now
            speech = rms_energy > silence_threshold
            if speech_activity is not None:
                if (frame.muted or acoustic_gate.is_speaking or frame.discontinuity
                        or now - frame.captured_at > MAX_AUDIO_BACKLOG_SEC
                        or (segmenter.last_sequence is not None and frame.sequence != segmenter.last_sequence + 1)):
                    speech_activity.reset()
                else:
                    try:
                        speech = await asyncio.to_thread(speech_activity.classify, block)
                    except Exception:
                        logging.exception('[SPEECH DETECTOR]: failed; discarding incomplete audio and reverting to RMS')
                        segmenter._reject('speech detector failed')
                        transcriber.generation += 1
                        speech_activity = None
                        continue
            now = time.monotonic()
            segment = segmenter.feed(
                frame, speech=speech,
                now=now, muted=acoustic_gate.is_speaking,
            )
            if segment.discarded_reason:
                logging.warning(
                    "[AUDIO DISCARD]: %s; affected capture discarded. Application mailbox dropped frames (cumulative)=%s",
                    segment.discarded_reason, audio_queue.dropped_frames,
                )
                if is_active_session:
                    await nc.publish("ultron.voice", json.dumps({
                        "speech": "I lost part of that recording. Please repeat the complete command."
                    }).encode())
            if segment.started:
                last_interaction_time = now
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
                if not transcriber.submit(full_audio, captured_at=frame.captured_at):
                    await report_transcription_discard("transcription queue overloaded; pending results invalidated")

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


        device_monitor.cancel()
        await asyncio.gather(device_monitor, return_exceptions=True)
        transcription_task.cancel()
        try:
            await transcription_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logging.exception("[STT WORKER]: worker stopped after failure")
        speaker_monitor.cancel()
        await asyncio.gather(speaker_monitor, return_exceptions=True)
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
