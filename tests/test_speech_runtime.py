"""Regression tests without an NVIDIA GPU, microphone, or model download."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

import speech_runtime as runtime


def test_environment_selects_model_and_strict_gpu(monkeypatch):
    monkeypatch.setenv("WHISPER_MODEL_SIZE", "large-v3")
    monkeypatch.setenv("WHISPER_DEVICE", "cuda")
    monkeypatch.setenv("WHISPER_LANGUAGE", "")
    config = runtime.SpeechConfig.from_env()
    assert (config.model, config.device, config.language) == ("large-v3", "cuda", None)


def test_listener_vocabulary_is_used_and_can_be_disabled():
    options = runtime.transcription_options(runtime.SpeechConfig())
    assert "Ultron" in options["initial_prompt"]
    assert options["vad_parameters"]["min_speech_duration_ms"] == 300
    assert runtime.transcription_options(runtime.SpeechConfig(use_vocabulary=False))["initial_prompt"] is None


@pytest.mark.parametrize("changes", [dict(device="gpu"), dict(compute_type="magic"), dict(model=""), dict(device_index=-1), dict(startup_timeout=0)])
def test_invalid_configuration_is_rejected(changes):
    with pytest.raises(ValueError):
        replace(runtime.SpeechConfig(), **changes).validate()


def test_discovers_wheel_bin_and_lib_and_installer(monkeypatch, tmp_path):
    wheel = tmp_path / "site" / "nvidia"
    paths = [wheel / "cudnn" / "bin", wheel / "cublas" / "lib", tmp_path / "CUDA" / "bin", tmp_path / "CUDA" / "bin" / "12.6"]
    for path in paths:
        path.mkdir(parents=True)
    monkeypatch.setattr(runtime.site, "getsitepackages", lambda: [str(tmp_path / "site")])
    monkeypatch.setattr(runtime.site, "getusersitepackages", lambda: str(tmp_path / "user"))
    monkeypatch.setenv("CUDA_PATH", str(tmp_path / "CUDA"))
    monkeypatch.delenv("ULTRON_CUDA_LIBRARY_DIRS", raising=False)
    assert set(paths).issubset(runtime.cuda_library_directories())


def test_relative_explicit_library_path_is_rejected(monkeypatch):
    monkeypatch.setenv("ULTRON_CUDA_LIBRARY_DIRS", "local-dlls")
    with pytest.raises(ValueError, match="absolute"):
        runtime.cuda_library_directories()


def test_windows_retains_handles_and_path_is_idempotent(monkeypatch, tmp_path):
    directory = str(tmp_path.resolve())
    handle = object()
    registrations = []
    def register(path):
        registrations.append(path)
        return handle
    env = {"PATH": "original"}
    monkeypatch.setattr(runtime, "os", SimpleNamespace(name="nt", environ=env, path=os.path, pathsep=os.pathsep, add_dll_directory=register))
    monkeypatch.setattr(runtime, "_DLL_HANDLES", {})
    monkeypatch.setattr(runtime, "cuda_library_directories", lambda: [tmp_path])
    runtime.configure_cuda_libraries()
    runtime.configure_cuda_libraries()
    assert runtime._DLL_HANDLES[directory] is handle
    assert registrations == [directory]
    assert env["PATH"].split(os.pathsep) == [directory, "original"]


def test_cpu_fallback_retains_exact_model(monkeypatch):
    calls = []
    def probe(config, device):
        calls.append((config.model, device))
        if device == "cuda":
            raise runtime.SpeechStartupError("missing cudnn64_9.dll")
        return {"ok": True}
    monkeypatch.setattr(runtime, "probe_runtime", probe)
    device, report = runtime.select_runtime(runtime.SpeechConfig(model="large-v3"))
    assert calls == [("large-v3", "cuda"), ("large-v3", "cpu")]
    assert device == "cpu"
    assert "cudnn64_9.dll" in report["cuda_error"]


def test_required_cuda_never_attempts_cpu(monkeypatch):
    calls = []
    def probe(config, device):
        calls.append(device)
        raise runtime.SpeechStartupError("native crash")
    monkeypatch.setattr(runtime, "probe_runtime", probe)
    with pytest.raises(runtime.SpeechStartupError, match="Required CUDA"):
        runtime.select_runtime(runtime.SpeechConfig(device="cuda"))
    assert calls == ["cuda"]


def test_explicit_cpu_skips_gpu_probe(monkeypatch):
    calls = []
    monkeypatch.setattr(runtime, "probe_runtime", lambda config, device: calls.append(device) or {"ok": True})
    assert runtime.select_runtime(runtime.SpeechConfig(device="cpu"))[0] == "cpu"
    assert calls == ["cpu"]


@pytest.mark.parametrize("exit_code,stdout,stderr", [(-6, "", "Could not load cudnn"), (1, 'ULTRON_SPEECH_RESULT={"ok": false, "error": "missing model"}', ""), (0, "", "no report"), (0, 'ULTRON_SPEECH_RESULT={', ""), (0, 'ULTRON_SPEECH_RESULT=[]', "")])
def test_native_crashes_and_bad_probe_reports_are_failures(monkeypatch, exit_code, stdout, stderr):
    monkeypatch.setattr(runtime.subprocess, "run", lambda *args, **kw: subprocess.CompletedProcess(args[0], exit_code, stdout, stderr))
    with pytest.raises(runtime.SpeechStartupError):
        runtime.probe_runtime(runtime.SpeechConfig(), "cuda")


def test_probe_uses_current_python_and_consumes_report(monkeypatch):
    def run(command, **kwargs):
        assert command[0] == sys.executable
        assert Path(command[1]).name == "speech_runtime.py"
        assert json.loads(command[3])["model"] == "small.en"
        assert kwargs["timeout"] == 300
        return subprocess.CompletedProcess(command, 0, 'download log\nULTRON_SPEECH_RESULT={"ok": true, "device": "cuda"}\n', "")
    monkeypatch.setattr(runtime.subprocess, "run", run)
    assert runtime.probe_runtime(runtime.SpeechConfig(), "cuda")["device"] == "cuda"


def test_probe_timeout_is_actionable(monkeypatch):
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 300)
    monkeypatch.setattr(runtime.subprocess, "run", timeout)
    with pytest.raises(runtime.SpeechStartupError, match="pre-download"):
        runtime.probe_runtime(runtime.SpeechConfig(), "cuda")


def test_cpu_model_creation_uses_same_model_int8_and_cache(monkeypatch):
    captured = {}
    def model(name, **kwargs):
        captured.update(name=name, **kwargs)
        return object()
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=model))
    monkeypatch.setattr(runtime, "configure_cuda_libraries", lambda: [])
    runtime._create_model(runtime.SpeechConfig(model="large-v3", local_files_only=True, download_root="cache"), "cpu")
    assert captured["name"] == "large-v3"
    assert captured["compute_type"] == "int8"
    assert captured["local_files_only"] is True
    assert captured["download_root"] == "cache"


def test_warmup_consumes_lazy_inference(monkeypatch):
    consumed = []
    class Model:
        def transcribe(self, audio, **kwargs):
            assert kwargs["vad_filter"] is False
            def generate():
                consumed.append(True)
                yield SimpleNamespace(text="")
            return generate(), None
    monkeypatch.setattr(runtime, "configure_cuda_libraries", lambda: [])
    monkeypatch.setitem(sys.modules, "ctranslate2", SimpleNamespace(get_cuda_device_count=lambda: 1, get_supported_compute_types=lambda *args: {"float16"}))
    monkeypatch.setattr(runtime, "_create_model", lambda config, device: Model())
    monkeypatch.setattr(runtime.importlib.metadata, "version", lambda name: "test")
    assert runtime._probe(runtime.SpeechConfig(), "cuda")["ok"]
    assert consumed == [True]
