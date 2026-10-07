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
settings that can be saved in `.env` beside `voice_listener.py`. The listener
loads that file at startup, regardless of the current working directory.
Existing process variables take precedence for temporary testing overrides.
After saving your settings once, start with
`.\.venv\Scripts\python.exe .\voice_listener.py`.
The brain, action daemon and NATS must still be running separately.

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

## Capture buffering and utterance limits

The listener uses a bounded, thread-safe mailbox with at most one pending
event-loop notification. At 16 kHz/1024 samples per block it holds 31 blocks
(approximately two seconds). Frames carry a sequence number, callback capture
time, capture-time TTS gate state and a discontinuity flag. Sample counts govern
the 1.4-second endpoint pause, including when buffered frames are consumed quickly.

A recording is rejected in its entirety if it loses audio, arrives more than
two seconds late, or would exceed the 15-second sample budget. The budget includes
pre-roll and the endpoint pause. The listener discards the remainder until a
complete 1.4-second quiet interval before accepting a new utterance. It never
transcribes a duration-limited fragment into an actionable command. Active
sessions receive a spoken request to repeat after a reported rejection; standby
rejections are logged without treating room noise as a user request.

Frames captured while TTS is gated stay muted even if consumed after playback.
If TTS interrupts an utterance, its remaining tail is discarded until quiet.
Calibration skips gated, stale and discontinuous frames, has a ten-second overall
deadline, and fails if audio stops arriving. The running listener also reports
an error and closes its stream if no frame arrives within five seconds.

Inference/audio consumption is still serial. A slow CPU inference can exceed the
backlog budget; the listener explicitly rejects damaged audio instead of silently
executing a fragment. Continuous recording/transcription workers, acoustic echo
cancellation, a larger recognition benchmark and macOS GPU support remain future
work.

For audio-buffer changes, include `test_audio_pipeline.py` in the regression
suite and validate on Windows with the UI, Ollama and TTS running:

- Single and consecutive commands, mid-sentence pauses shorter than 1.4 seconds,
  session timeout/reactivation, and microphone noise calibration.
- An uninterrupted utterance longer than 15 seconds: expect `[AUDIO DISCARD]`,
  no transcription/intent for that utterance, and recovery after a full quiet gap.
- TTS output never becoming a new user request, and a deliberate microphone
  interruption producing a clear failure rather than false listening readiness.

## References

- [Faster-Whisper GPU requirements](https://github.com/SYSTRAN/faster-whisper#gpu)
- [NVIDIA cuDNN Windows installation](https://docs.nvidia.com/deeplearning/cudnn/installation/latest/windows.html)
- [cuDNN 9.10.2.21 Windows wheel](https://pypi.org/project/nvidia-cudnn-cu12/9.10.2.21/)
- [cuBLAS 12.6.4.1 wheels](https://pypi.org/project/nvidia-cublas-cu12/12.6.4.1/)
