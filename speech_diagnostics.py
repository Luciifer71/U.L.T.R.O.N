"""JSON speech health report; works without NATS, Ollama, or the UI."""
from __future__ import annotations

import argparse
from dataclasses import replace
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import tempfile
import wave

from speech_runtime import SpeechConfig, configure_cuda_libraries, probe_runtime


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--model", help="Override WHISPER_MODEL_SIZE")
    parser.add_argument("--list-mics", action="store_true", help="List inputs without loading a model")
    parser.add_argument("--mic-device", type=int, help="SoundDevice input device ID")
    parser.add_argument("--record-seconds", type=float, help="Record a test utterance and transcribe it")
    parser.add_argument("--audio", type=Path, help="Transcribe an existing recording instead")
    parser.add_argument("--save-audio", type=Path, help="Keep the recording as a WAV for model comparisons")
    parser.add_argument("--no-vocabulary", action="store_true", help="Compare decoding without the listener's vocabulary hint")
    args = parser.parse_args()
    if args.record_seconds is not None and not 1 <= args.record_seconds <= 30:
        parser.error("--record-seconds must be between 1 and 30")
    if args.audio and args.record_seconds:
        parser.error("Choose --audio or --record-seconds")
    if args.save_audio and (not args.record_seconds or args.list_mics):
        parser.error("--save-audio requires --record-seconds")
    report = {"ok": False, "python": sys.executable, "platform": platform.platform()}
    try:
        report["library_directories"] = configure_cuda_libraries()
        report["packages"] = {}
        for name in ("faster-whisper", "ctranslate2", "nvidia-cublas-cu12", "nvidia-cudnn-cu12", "sounddevice"):
            try:
                report["packages"][name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                report["packages"][name] = None
        if args.list_mics:
            import sounddevice as sd
            report["microphones"] = [dict(device, id=index) for index, device in enumerate(sd.query_devices()) if device["max_input_channels"] > 0]
            report["ok"] = True
        else:
            config = replace(SpeechConfig.from_env(), device=args.device)
            config = replace(config, use_vocabulary=not args.no_vocabulary)
            if args.model:
                config = replace(config, model=args.model)
            if args.audio:
                if not args.audio.is_file():
                    raise ValueError(f"Audio file does not exist: {args.audio}")
                report["speech"] = probe_runtime(config, args.device, str(args.audio))
            elif args.record_seconds:
                if args.save_audio and args.save_audio.exists():
                    raise FileExistsError(f"Recording already exists: {args.save_audio}; choose a new filename")
                import sounddevice as sd
                import numpy as np
                sd.check_input_settings(device=args.mic_device, samplerate=16000, channels=1, dtype="float32")
                print("Speak a test command now.", file=sys.stderr)
                recording = sd.rec(int(args.record_seconds * 16000), samplerate=16000,
                                   channels=1, dtype="float32", device=args.mic_device)
                sd.wait()
                report["recording"] = {
                    "rms": float(np.sqrt(np.mean(recording ** 2))),
                    "peak": float(np.max(np.abs(recording))),
                    "clipping_fraction": float(np.mean(np.abs(recording) >= 0.999)),
                }
                with tempfile.TemporaryDirectory(prefix="ultron-speech-") as directory:
                    audio = Path(directory) / "test.wav"
                    with wave.open(str(audio), "wb") as output:
                        output.setnchannels(1)
                        output.setsampwidth(2)
                        output.setframerate(16000)
                        output.writeframes((np.clip(recording, -1, 1) * 32767).astype("<i2").tobytes())
                    if args.save_audio:
                        # Exclusive creation preserves any existing user recording.
                        with args.save_audio.open("xb") as output:
                            output.write(audio.read_bytes())
                        report["saved_audio"] = str(args.save_audio.resolve())
                    report["speech"] = probe_runtime(config, args.device, str(audio))
            else:
                report["speech"] = probe_runtime(config, args.device)
                import sounddevice as sd
                report["microphones"] = [dict(device, id=index) for index, device in enumerate(sd.query_devices()) if device["max_input_channels"] > 0]
                sd.check_input_settings(device=args.mic_device, samplerate=16000, channels=1, dtype="float32")
            report["ok"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
