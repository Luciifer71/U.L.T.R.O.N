import json
import sys
from types import SimpleNamespace
import wave

import numpy as np

import speech_diagnostics as diagnostics


def prepare(monkeypatch, arguments):
    monkeypatch.setattr(sys, "argv", ["speech_diagnostics.py", *arguments])
    monkeypatch.setattr(diagnostics, "configure_cuda_libraries", lambda: [])
    sd = SimpleNamespace(
        query_devices=lambda: [dict(name="test mic", max_input_channels=1)],
        check_input_settings=lambda **kwargs: None,
        rec=lambda frames, **kwargs: np.full((frames, 1), 0.1, dtype=np.float32),
        wait=lambda: None,
    )
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    return sd


def test_list_microphones_does_not_load_model(monkeypatch, capsys):
    prepare(monkeypatch, ["--list-mics"])
    monkeypatch.setattr(diagnostics, "probe_runtime", lambda *args: (_ for _ in ()).throw(AssertionError("model must not load")))
    assert diagnostics.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["microphones"][0]["id"] == 0


def test_gpu_failure_reports_error_and_nonzero_exit(monkeypatch, capsys):
    prepare(monkeypatch, ["--device", "cuda"])
    def unavailable(*args):
        raise RuntimeError("cudnn missing")
    monkeypatch.setattr(diagnostics, "probe_runtime", unavailable)
    assert diagnostics.main() == 1
    assert "cudnn missing" in json.loads(capsys.readouterr().out)["error"]


def test_recording_transcribes_pcm_and_deletes_temporary_file(monkeypatch, capsys):
    prepare(monkeypatch, ["--device", "cuda", "--record-seconds", "1"])
    paths = []
    def probe(config, device, path):
        paths.append(path)
        with wave.open(path) as audio:
            assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (16000, 1, 2)
            assert audio.getnframes() == 16000
        return {"ok": True, "device": device, "transcript": "open calculator"}
    monkeypatch.setattr(diagnostics, "probe_runtime", probe)
    assert diagnostics.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["speech"]["transcript"] == "open calculator"
    assert report["recording"]["clipping_fraction"] == 0
    assert not diagnostics.Path(paths[0]).exists()


def test_saved_recording_survives_inference_failure(monkeypatch, capsys, tmp_path):
    audio = tmp_path / "command.wav"
    prepare(monkeypatch, ["--record-seconds", "1", "--save-audio", str(audio)])
    def fail(*args):
        raise RuntimeError("GPU unavailable")
    monkeypatch.setattr(diagnostics, "probe_runtime", fail)
    assert diagnostics.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report["saved_audio"] == str(audio.resolve())
    with wave.open(str(audio)) as recording:
        assert recording.getnframes() == 16000


def test_saved_recording_does_not_overwrite_existing_file(monkeypatch, capsys, tmp_path):
    audio = tmp_path / "command.wav"
    audio.write_bytes(b"preserve this recording")
    prepare(monkeypatch, ["--record-seconds", "1", "--save-audio", str(audio)])
    assert diagnostics.main() == 1
    assert "FileExistsError" in json.loads(capsys.readouterr().out)["error"]
    assert audio.read_bytes() == b"preserve this recording"


def test_existing_audio_can_decode_without_vocabulary(monkeypatch, capsys, tmp_path):
    audio = tmp_path / "command.wav"
    audio.write_bytes(b"input")
    prepare(monkeypatch, ["--audio", str(audio), "--no-vocabulary"])
    def probe(config, device, path):
        assert config.use_vocabulary is False
        assert path == str(audio)
        return {"ok": True}
    monkeypatch.setattr(diagnostics, "probe_runtime", probe)
    assert diagnostics.main() == 0
