"""Shared speech startup and isolated native-runtime validation.

Importing this module does not import CTranslate2 or require audio hardware.
Windows DLL directory handles must stay alive for the entire process.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import site
import subprocess
import sys
import time

_DLL_HANDLES: dict[str, object] = {}
_RESULT_PREFIX = "ULTRON_SPEECH_RESULT="
SYSTEM_PROMPT_VOCAB = (
    "Ultron, Hey Ultron, system command, open application, "
    "system diagnostics, task manager, terminal, lock workstation, "
    "run process, browser, calculator, cmd."
)


class SpeechStartupError(RuntimeError):
    pass


@dataclass(frozen=True)
class SpeechConfig:
    model: str = "small.en"
    device: str = "auto"
    compute_type: str = "float16"
    device_index: int = 0
    language: str | None = "en"
    download_root: str | None = None
    local_files_only: bool = False
    startup_timeout: int = 300
    use_vocabulary: bool = True

    @classmethod
    def from_env(cls) -> "SpeechConfig":
        config = cls(
            model=os.getenv("WHISPER_MODEL_SIZE", "small.en").strip(),
            device=os.getenv("WHISPER_DEVICE", "auto").strip().lower(),
            compute_type=os.getenv("WHISPER_CUDA_COMPUTE_TYPE", "float16").strip(),
            device_index=int(os.getenv("WHISPER_DEVICE_INDEX", "0")),
            language=os.getenv("WHISPER_LANGUAGE", "en").strip() or None,
            download_root=os.getenv("WHISPER_DOWNLOAD_ROOT") or None,
            local_files_only=os.getenv("WHISPER_LOCAL_FILES_ONLY", "0").lower() in {"1", "true"},
            startup_timeout=int(os.getenv("WHISPER_STARTUP_TIMEOUT", "300")),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.device not in {"auto", "cuda", "cpu"}:
            raise ValueError("WHISPER_DEVICE must be auto, cuda, or cpu")
        if self.compute_type not in {"float16", "float32", "int8_float16", "int8_float32"}:
            raise ValueError("Unsupported WHISPER_CUDA_COMPUTE_TYPE")
        if not self.model or self.device_index < 0 or self.startup_timeout <= 0:
            raise ValueError("Model, device index, and startup timeout must be valid")


def transcription_options(config: SpeechConfig) -> dict:
    """The listener and recorded-audio diagnostics use identical decoding."""
    return dict(
        beam_size=5, language=config.language, vad_filter=True,
        vad_parameters=dict(min_speech_duration_ms=300, threshold=0.45,
                            min_silence_duration_ms=1000),
        no_speech_threshold=0.6, log_prob_threshold=-1.0,
        compression_ratio_threshold=2.4, condition_on_previous_text=False,
        initial_prompt=SYSTEM_PROMPT_VOCAB if config.use_vocabulary else None,
    )


def cuda_library_directories() -> list[Path]:
    """Discover wheel and official installer layouts; never search the cwd."""
    candidates: list[Path] = []
    for value in os.getenv("ULTRON_CUDA_LIBRARY_DIRS", "").split(os.pathsep):
        if value:
            path = Path(value).expanduser()
            if not path.is_absolute():
                raise ValueError("ULTRON_CUDA_LIBRARY_DIRS entries must be absolute paths")
            candidates.append(path)
    roots = list(site.getsitepackages()) + [site.getusersitepackages()]
    for root in roots:
        for component in ("cublas", "cudnn", "cuda_runtime", "nvjitlink"):
            for folder in ("bin", "lib"):
                candidates.append(Path(root) / "nvidia" / component / folder)
    for key in sorted(os.environ):
        if key in {"CUDA_PATH", "CUDA_HOME", "CUDNN_PATH", "CUDNN_HOME"} or key.startswith("CUDA_PATH_V12_"):
            root = Path(os.environ[key]).expanduser()
            if root.is_absolute():
                candidates.extend((root / "bin", root / "lib", root))
    if os.name == "nt":
        program_files = Path(os.getenv("ProgramFiles", "C:/Program Files"))
        candidates.extend(sorted((program_files / "NVIDIA GPU Computing Toolkit" / "CUDA").glob("v12.*/bin"), reverse=True))
        candidates.extend(sorted((program_files / "NVIDIA" / "CUDNN").glob("v9*/bin"), reverse=True))
    # Recent cuDNN installers also use bin/12.x.
    expanded = []
    for candidate in candidates:
        expanded.append(candidate)
        if candidate.name == "bin" and candidate.is_dir():
            expanded.extend(sorted(candidate.glob("12*"), reverse=True))
    return list(dict.fromkeys(path.resolve() for path in expanded if path.is_dir()))


def configure_cuda_libraries() -> list[str]:
    directories = [str(path) for path in cuda_library_directories()]
    if os.name == "nt":
        for directory in directories:
            if directory not in _DLL_HANDLES:
                # Retain handles: closing/collecting one removes the directory.
                _DLL_HANDLES[directory] = os.add_dll_directory(directory)
        # CTranslate2 also uses native LoadLibrary; it needs PATH as well.
        current = os.environ.get("PATH", "").split(os.pathsep)
        os.environ["PATH"] = os.pathsep.join(dict.fromkeys(directories + current))
    # Linux requires LD_LIBRARY_PATH before Python starts; do not pretend a
    # runtime environment edit changes the dynamic loader's search path.
    return directories


def _create_model(config: SpeechConfig, device: str):
    configure_cuda_libraries()
    from faster_whisper import WhisperModel
    return WhisperModel(
        config.model,
        device=device,
        device_index=config.device_index,
        compute_type=config.compute_type if device == "cuda" else "int8",
        download_root=config.download_root,
        local_files_only=config.local_files_only,
    )


def _probe(config: SpeechConfig, device: str, audio: str | None = None) -> dict:
    """Runs only in a child: some missing native libraries abort the process."""
    directories = configure_cuda_libraries()
    import ctranslate2
    import numpy as np
    if device == "cuda":
        count = ctranslate2.get_cuda_device_count()
        if config.device_index >= count:
            raise SpeechStartupError(f"CUDA device {config.device_index} unavailable; detected {count}")
        supported = ctranslate2.get_supported_compute_types("cuda", config.device_index)
        if config.compute_type not in supported:
            raise SpeechStartupError(f"{config.compute_type} unsupported; supported: {sorted(supported)}")
    model = _create_model(config, device)
    started = time.monotonic()
    segments, _ = model.transcribe(
        np.zeros(16000, dtype=np.float32), beam_size=1, vad_filter=False,
        language=config.language,
    )
    list(segments)  # Model construction alone does not exercise cuDNN/cuBLAS.
    result = {
        "ok": True, "model": config.model, "device": device,
        "compute_type": config.compute_type if device == "cuda" else "int8",
        "warmup_seconds": round(time.monotonic() - started, 3),
        "library_directories": directories,
        "versions": {name: importlib.metadata.version(name) for name in ("faster-whisper", "ctranslate2")},
    }
    if audio:
        started = time.monotonic()
        segments, info = model.transcribe(audio, **transcription_options(config))
        result.update(transcript=" ".join(s.text.strip() for s in segments),
                      audio_seconds=info.duration,
                      inference_seconds=round(time.monotonic() - started, 3),
                      vocabulary_hint=config.use_vocabulary)
    return result


def probe_runtime(config: SpeechConfig, device: str, audio: str | None = None) -> dict:
    config.validate()
    command = [sys.executable, str(Path(__file__).resolve()), "--probe-child",
               json.dumps(asdict(config)), device]
    if audio:
        command.append(str(Path(audio).resolve()))
    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   timeout=config.startup_timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise SpeechStartupError(f"Speech startup exceeded {config.startup_timeout}s; pre-download the model or increase WHISPER_STARTUP_TIMEOUT") from exc
    result = None
    for line in completed.stdout.splitlines():
        if line.startswith(_RESULT_PREFIX):
            try:
                result = json.loads(line[len(_RESULT_PREFIX):])
            except json.JSONDecodeError as exc:
                raise SpeechStartupError("Native probe returned malformed JSON") from exc
    if result is not None and not isinstance(result, dict):
        raise SpeechStartupError("Native probe returned an invalid report")
    if completed.returncode != 0 or not result or not result.get("ok"):
        detail = (result or {}).get("error") or completed.stderr[-4000:] or "Native process exited without a diagnostic"
        raise SpeechStartupError(f"{device} probe exit {completed.returncode}: {detail}")
    return result


def select_runtime(config: SpeechConfig) -> tuple[str, dict]:
    config.validate()
    if config.device == "cpu":
        return "cpu", probe_runtime(config, "cpu")
    try:
        return "cuda", probe_runtime(config, "cuda")
    except SpeechStartupError as exc:
        if config.device == "cuda":
            raise SpeechStartupError(
                f"Required CUDA speech runtime failed: {exc}. Run python speech_diagnostics.py --device cuda. "
                "Use matching CUDA 12 cuBLAS and cuDNN 9 libraries in this Python environment."
            ) from exc
        logging.warning("[WHISPER]: CUDA unavailable: %s. CPU fallback keeps model %s; latency may increase.", exc, config.model)
        report = probe_runtime(config, "cpu")
        report["cuda_error"] = str(exc)
        return "cpu", report


def load_whisper_model(config: SpeechConfig):
    device, report = select_runtime(config)
    model = _create_model(config, device)
    logging.info("[WHISPER]: model=%s device=%s compute=%s warmup=%.3fs",
                 config.model, device, report["compute_type"], report["warmup_seconds"])
    return model, device, report


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--probe-child":
        try:
            config = SpeechConfig(**json.loads(sys.argv[2]))
            config.validate()
            result = _probe(config, sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
        except Exception as exc:
            print(_RESULT_PREFIX + json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
            sys.exit(1)
        print(_RESULT_PREFIX + json.dumps(result))
