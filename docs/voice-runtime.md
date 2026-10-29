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
$env:AUDIO_INPUT_MODE = "pinned"
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
  run `python -m pytest -q tests/test_speech_runtime.py tests/test_voice_listener.py tests/test_speech_diagnostics.py`.
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

## Speech output fails with HTTP 403

Microphone recognition and spoken replies use separate services. If commands
execute but the action daemon reports `ULTRON VOICE ERROR` with HTTP 403,
troubleshoot Edge TTS first. A `SPEAKING` log is emitted before synthesis and
is not proof that audio played. Changing Whisper or the reasoning model does
not address this speech-service response.

Stop running Ultron components. From the repository root, check the installed
package and test synthesis independently:

```powershell
.\.venv\Scripts\python.exe -m pip show edge-tts
.\.venv\Scripts\python.exe -m edge_tts --voice en-US-ChristopherNeural --text "Ultron speech test." --write-media "$env:TEMP\ultron-tts-test.mp3"
```

Only after synthesis succeeds, open the generated file:

```powershell
Start-Process "$env:TEMP\ultron-tts-test.mp3"
```

For a 7.2.8 installation returning 403, test the following targeted update:

```powershell
.\.venv\Scripts\python.exe -m pip install edge-tts==7.3.1
```

Repeat synthesis and playback after the update. Upstream 7.3.0 added updated
service-token support; 7.3.1 corrected server-date parsing. On 15 October 2026,
the project's Windows tester confirmed audible standalone playback after this
update. Integrated daemon playback still requires a separate check. This is
not a guarantee that every 403 has the same cause.

This troubleshooting step changes the local virtual environment. Check the
branch's requirements pin before reinstalling all dependencies, as an older pin
can restore the older package. If failure persists, record the installed version
and error status without sharing the full request URL. Keep generated audio out
of Git. Before declaring recovery, run `verify_ultron.py`, restart the components
and confirm that both the greeting and an action reply are audible.

Upstream release notes: [7.3.0](https://github.com/rany2/edge-tts/releases/tag/7.3.0)
and [7.3.1](https://github.com/rany2/edge-tts/releases/tag/7.3.1).

## References

- [Faster-Whisper GPU requirements](https://github.com/SYSTRAN/faster-whisper#gpu)
- [NVIDIA cuDNN Windows installation](https://docs.nvidia.com/deeplearning/cudnn/installation/latest/windows.html)
- [cuDNN 9.10.2.21 Windows wheel](https://pypi.org/project/nvidia-cudnn-cu12/9.10.2.21/)
- [cuBLAS 12.6.4.1 wheels](https://pypi.org/project/nvidia-cublas-cu12/12.6.4.1/)

### Uncertain transcription

Ultron now rejects an entire utterance if any decoded segment has average log
probability below -1.0 or compression ratio above 2.4, matching the existing
decoder thresholds. During an active session it asks for the complete request
again. It never drops just the uncertain target or replaces it with a guessed
application or filename. Ambient silence still produces no spoken prompt.
These are heuristics, not calibrated certainty: a wrong but confident transcript
can still pass, and quiet legitimate speech can be rejected. Recorded-audio and
live-device evaluation are still needed to measure recognition accuracy.

## Avoid overlapping launcher sessions

Run `start-qwen3-trial.cmd` once per session. If a launcher reports model warmup,
wait for completion or its reported timeout before retrying. Re-running the
launcher while the first set of components remains active can create overlapping
listeners, brains or speech daemons and make repeated replies harder to diagnose.

For a clean restart, cancel any launcher still waiting, then press Ctrl+C in each
Ultron component window. Start the launcher once and wait for the voice listener's
`STANDBY MODE` message after calibration before speaking. Docker and Ollama can
remain running between sessions.

Model loading and microphone readiness are separate milestones. An Ollama log
showing all model layers offloaded to the GPU confirms that model's GPU placement;
it does not confirm Whisper initialization, microphone capture or audible playback.
If startup fails, retain the final error and collect a support bundle using the
[report instructions](support-bundles.md).

## Repeated wake words and first-response latency

Repeated leading wake phrases, such as “Hey Ultron, Hey Ultron,” now produce one
wake acknowledgement and no leftover greeting for the model. A following command
is retained; an occurrence of “Ultron” inside a filename is not removed.
“What all tasks can you do for me?” uses the factual capability response.

The launcher exercises up to eight generated tokens before starting components.
Its `[WARMUP TIMING]` line separates wall time, model loading, prompt evaluation
and token generation when Ollama supplies those fields. Qwen3 runtime requests
retain the model for ten minutes by default, matching startup; explicit caller
retention values still take precedence. Retention uses memory while idle.
These changes avoid unnecessary model requests and exercise generation during
startup; they do not guarantee faster disk loading or eliminate GPU/driver stalls.

To check a slow start, retain the warmup timing line and compare it with the first
`[OLLAMA TIMING]` request. A long load phase and slow generation are different
problems. Capture available RAM/GPU memory at the time of the delay before
attributing it to memory pressure. A later snapshot cannot establish the cause.

Audio-driver overflow rejects the affected capture and waits for a clean quiet
gap. A recording completed before that overflow can still finish transcription;
its adjacent log entry does not by itself mean damaged audio was dispatched.

### Automatic microphone selection and recovery

With `AUDIO_INPUT_MODE=auto` (the default), the listener prefers an available headset input,
then a laptop microphone array, then another physical microphone. Output-only
headphones do not replace the laptop microphone. Windows device names are used
as a heuristic; this detects an exposed input, not whether a headset is being worn.
Legacy `AUDIO_INPUT_DEVICE` values are ignored in auto mode, with a startup log.
To intentionally pin a device, set both `AUDIO_INPUT_MODE=pinned` and
`AUDIO_INPUT_DEVICE`. No private `.env` file or Windows audio default is modified.

A separate, bounded helper checks the device inventory every 10 seconds because
PortAudio caches its initial device list. Healthy streams are not periodically
restarted. A changed inventory or five seconds without capture frames triggers
stream reopening and calibration. Failed runtime recovery retries automatically;
incomplete and pending old-device commands are invalidated. A device switch
returns to standby: wait for `[MIC READY]` and repeat the complete wake request.
A headset that cannot open falls back to the next available microphone. Bluetooth
and analog headset support depends on the Windows driver exposing a recording
endpoint. Microphone privacy denial and physical mute cannot be overridden.

`[MIC STATE]` reports speech suppression and resumption. `[MIC HEALTH]` reports
selected device, peak input RMS, threshold, gate and session state every 10 seconds;
it does not record raw audio. These logs distinguish a quiet/muted input from a
paused echo gate or a dead stream. Silent but still delivered frames do not prove
a driver failure, so silence alone does not trigger disruptive restarts.

The 25-second inactivity timeout is unchanged. Listening remains suppressed during
TTS to avoid self-triggering; voice interruption is not implemented. Synthesis is
bounded to 20 seconds and playback to 90 seconds, with gate release on completion,
error, cancellation or timeout. Capability answers retain full terminal text but
use a shorter spoken summary. `stop-ultron-speech.cmd` can stop speech immediately.


### Speech boundaries and short acknowledgements

The listener now uses Faster-Whisper 1.2.1's bundled Silero detector on a bounded
one-second rolling window, off the audio callback and event loop. Only the newest
64 ms determines speech activity; a 1.4-second non-speech interval still ends a
recording. RMS remains diagnostic rather than the sole trigger, allowing steady
non-speech noise to end an utterance. Detection state resets across playback,
device switches and damaged frames. The 15-second maximum still **rejects** an
unfinished utterance; it does not execute a truncated command. Initialization
failure logs an explicit RMS fallback. Runtime detector failure invalidates the
current capture and pending recognition before falling back.

`[MIC HEALTH]` shows `endpoint=silero` or `endpoint=rms`. This does not establish
accuracy on every microphone, accent or background sound; the detector can still
misclassify speech. No user audio is recorded or uploaded by this change.

A short acknowledgement such as `Very good. Hey Ultron` may precede a direct wake
address. This is a bounded allowlist, not an arbitrary search through quoted or
reported commands. Capability variants including the observed `give-abilities`
transcription use the factual fast reply. The voice daemon now honors a separate
`speech` field, including explicit empty speech, instead of preferring full `text`.
