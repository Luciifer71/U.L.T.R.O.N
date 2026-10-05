# Speech runtime setup and acceptance

This change repairs speech runtime initialization. It does not establish that
ULTRON as a whole is production ready. Windows GPU and microphone acceptance
must pass on the target machine before merging/releasing this change.

## Windows NVIDIA setup

Use 64-bit Python 3.11 or 3.12 and the same virtual environment used to run the
listener. Check `nvidia-smi` first; a working NVIDIA driver is required. The CUDA
version shown by `nvidia-smi` describes driver capability, not installed cuDNN.
The pinned stack is Faster-Whisper 1.2.1, CTranslate2 4.8.2, CUDA 12 cuBLAS
12.6.4.1, and cuDNN 9.10.2.21. NVIDIA publishes Windows x64 wheels for these
libraries; a separate PyTorch CUDA installation is unnecessary for this backend.
The optional NVIDIA libraries are large downloads and do not install a driver.

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-speech-windows.txt
$env:WHISPER_DEVICE = "cuda"
$env:WHISPER_MODEL_SIZE = "small.en"
$env:WHISPER_CUDA_COMPUTE_TYPE = "float16"
.\.venv\Scripts\python.exe speech_diagnostics.py --device cuda
```

First startup downloads the model unless it is already cached. For offline
deployment, pre-download it, set `WHISPER_DOWNLOAD_ROOT` to the cache directory,
and set `WHISPER_LOCAL_FILES_ONLY=1`. For a local CTranslate2 model directory,
set `WHISPER_MODEL_SIZE` to its absolute path. Model files must be included in
the deployment plan separately from Python dependencies. Increase
`WHISPER_STARTUP_TIMEOUT` from 300 seconds if the initial download needs longer.

The report must contain `ok: true` and `speech.device: cuda`, and show the
intended model and compute type. It performs actual inference and consumes the
lazy segment iterator; merely detecting an NVIDIA GPU is insufficient.
Startup probing is isolated because native CUDA/cuDNN failures may terminate a
process without raising a Python exception. The child exits before the listener
loads its model, so the two models do not occupy VRAM concurrently.

If using official CUDA/cuDNN installers instead of Python wheels, discovery
includes `CUDA_PATH`, `CUDA_PATH_V12_*`, `CUDNN_PATH`, `CUDNN_HOME`, standard
Windows installer locations, and `bin/12.x` subdirectories. For custom locations:

```powershell
$env:ULTRON_CUDA_LIBRARY_DIRS = "C:\CUDA\bin;C:\cuDNN\bin"
```

Use absolute directories containing the DLLs. Do not copy random DLLs into the
repository or Windows system directories. Windows registers discovered DLL
directories before importing Faster-Whisper/CTranslate2, retains their handles,
and updates the process PATH for native loading. Linux requires library paths
in `LD_LIBRARY_PATH` **before** starting Python; the module does not claim to
repair the Linux dynamic loader by changing that variable after startup.

## Microphone and recognition checks

```powershell
.\.venv\Scripts\python.exe speech_diagnostics.py --list-mics
.\.venv\Scripts\python.exe speech_diagnostics.py --device cuda --mic-device 1 --record-seconds 6
$env:AUDIO_INPUT_DEVICE = "1"
.\.venv\Scripts\python.exe voice_listener.py
```

Replace `1` with your input device ID. The listener accepts an ID or a device
name through `AUDIO_INPUT_DEVICE`. The diagnostic checks mono float32 capture
at 16 kHz, reports recording RMS, peak and clipping fraction, and transcribes
the test utterance without publishing intents. A failed input device now raises
a startup error; a microphone that delivers no audio times out during calibration
instead of hanging indefinitely. Grant microphone permission to your terminal.
The temporary diagnostic recording is deleted after the test. To keep one for
repeatable model comparisons, add `--save-audio command.wav`. An existing file
is preserved and causes an error; choose a new filename for another recording.
The file is kept even if subsequent inference fails. Diagnostics and the listener
share decoding/VAD settings and the same vocabulary hint. Use `--no-vocabulary`
with `--audio command.wav` to compare decoding without the hint. A vocabulary
hint can influence recognition; it does not prove correct recognition by itself.

The listener keeps its existing English vocabulary prompt, wake-word handling,
VAD parameters, NATS subjects and UI listening events. `.env.example` documents
**process environment variables**; this listener does not automatically load
a `.env` file. PowerShell variables above apply to the current terminal session.

## Model choice and fallback policy

`WHISPER_DEVICE=cuda` requires successful GPU initialization and never starts a
CPU listener. `auto` (the compatibility default) attempts CUDA, logs the failure
reason, then verifies CPU int8 inference with the **same model**. `cpu` skips GPU
initialization. No code silently substitutes `base.en` for another model.
CPU/GPU choice primarily affects latency; model changes, quantization, recording
quality, language and segmentation can affect recognition. Do not assume that
CPU inference itself necessarily reduces accuracy, or that float16 guarantees
perfect transcription.

The default remains `small.en` to preserve existing behavior. To evaluate a
larger multilingual model, use `WHISPER_MODEL_SIZE=large-v3` and
`WHISPER_CUDA_COMPUTE_TYPE=int8_float16`, then compare it with float16 on the same
recordings. This is an evaluation candidate, not a claim of best accuracy or a
validated VRAM budget. Ollama, Whisper and the WebGPU UI share GPU memory; run
acceptance with all three active. Do not select a deployment model solely by
its size or an unrelated published benchmark.

`WHISPER_LANGUAGE=en` selects English; an empty value enables language detection.
`WHISPER_DEVICE_INDEX` selects the NVIDIA device, defaulting to 0. Diagnostics
exposes `--model` and `--audio` for repeatable comparisons using saved recordings.
Use recordings of the user's commands and accent, including quiet speech,
background noise, pauses, wake words, short targets and non-command audio.
Measure command transcription errors and false activations, as well as latency.

## Merge/release gate

- Install the development test runner with `python -m pip install pytest`, then
  run `python -m pytest -q test_speech_runtime.py test_voice_listener.py test_speech_diagnostics.py`.
- On Windows, install the speech requirements in the intended environment and
  obtain a successful strict CUDA health report and microphone recording test.
- Test the complete listener → brain → action → TTS loop, including TTS gating,
  consecutive requests, NATS reconnection and clean shutdown.
- Test the chosen model with Ollama and all UI modes active; verify sufficient
  VRAM and acceptable latency without automatic model changes.
- Confirm strict mode reports missing libraries and exits, while automatic
  mode logs the reason and preserves the selected model on CPU.

The existing listener still has a serial inference/audio-consumption loop and
an unbounded capture queue. Continuous-utterance limits, backlog management and
echo suppression need separate measured audio-pipeline work. This patch does
not claim that those issues, or macOS GPU support, have been solved.

## References

- [Faster-Whisper GPU requirements](https://github.com/SYSTRAN/faster-whisper#gpu)
- [NVIDIA cuDNN Windows installation](https://docs.nvidia.com/deeplearning/cudnn/installation/latest/windows.html)
- [cuDNN 9.10.2.21 Windows wheel](https://pypi.org/project/nvidia-cudnn-cu12/9.10.2.21/)
- [cuBLAS 12.6.4.1 wheels](https://pypi.org/project/nvidia-cublas-cu12/12.6.4.1/)
