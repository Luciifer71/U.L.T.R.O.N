# Getting started

Windows is the primary integrated runtime. Run commands from the repository root
unless a different directory is specified. For authorized use under the
[existing ownership terms](../README.md#license--ownership).

## Setup · Windows


Use Python 3.12 or 3.13, Git and Ollama. Docker Desktop is optional (see fast startup below). The optional visual UI also
requires Node.js/npm compatible with its Vite dependency. Full speech/vision
installation depends on your platform and native dependencies.

Run in PowerShell:

```powershell
git clone https://github.com/Luciifer71/U.L.T.R.O.N.git Ultron-core
cd Ultron-core
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install keyboard psutil pyperclip duckduckgo-search
Copy-Item .env.example .env
ollama pull qwen3:8b
```

For an existing checkout, preserve your `.env`; do not overwrite local settings.
The default planner is `qwen3:8b`. `LLM_MODEL`, `OLLAMA_HOST` and `NATS_URL` are
configurable. See [.env.example](../.env.example) for runtime settings and
[model evaluation](model-evaluation.md) for benchmark scope.

For supported NVIDIA speech inference on x64 Windows:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements/speech-windows.txt
```

This does not install an NVIDIA driver. Follow the [voice runtime guide](voice-runtime.md)
for CUDA validation, microphone selection and fallback behavior.

### Optional integrations

- **Google:** follow [account setup, privacy and coverage](google-updates.md).
  Installation does not connect an account. Google consent is required; tokens
  use Windows Credential Manager. Access cannot send or delete emails.
- **YouTube playback:** run `scripts/windows/setup-youtube-playback.cmd` and read the
  [playback guide](youtube-playback.md). Edge is the default; installed Chrome
  can be selected with `ULTRON_BROWSER_CHANNEL=chrome`. Profiles are isolated.
- **Knowledge/gestures:** separate utilities and dependencies, not prerequisites
  for the basic voice/app workflow.

Local model inference requires no paid model API. Edge TTS, Google and website
features need network access; local-first does not mean every feature is offline.

## Run

From the repository root, after setup:

```powershell
.\start-ultron.cmd
```

The launcher starts NATS and Ollama at the same time, opens the action daemon,
brain and vision service as soon as the bus is up, warms the model, then opens the
listener. It ends with a `[STARTUP TIMING]` report of each step. Wait for `STANDBY MODE` before
saying “Hey Ultron”. The launcher defaults to Qwen3:8b. Use `.\start-ultron.cmd --menu` to select a model or `.\start-ultron.cmd --qwen25` for Qwen2.5:7b. The legacy Qwen3 launcher remains available as a compatibility wrapper.
The Qwen3 profile uses thinking off, context 4096, temperature 0 and seed 42 without rewriting `.env`.

### Fast startup (once)

Docker Desktop can take minutes to boot. Install the native message bus once and
the launcher no longer needs Docker for it (it starts in under a second):

```powershell
.\.venv\Scripts\python.exe .\run_ultron.py setup-nats
```

This downloads the official `nats-server` 2.10.29 for Windows (the same version as
the Docker image), refuses it unless its SHA-256 matches, and puts it in
`tools\nats\` (not committed). It runs with `config/nats-server.native.conf`,
which listens on `127.0.0.1` only. Without it, the launcher falls back to Docker.

If the timing report shows a long **Model warmup**, the time is Ollama loading the
model; the Ollama window shows the load. The launcher then prints
`[MODEL PLACEMENT]`: if it warns that part of the model is on the CPU, loading and
every reply are many times slower. Run `ollama ps` (the PROCESSOR column should say
`100% GPU`), close other GPU-heavy apps, and make sure the NVIDIA driver is current. Keeping the Ollama models folder
on an SSD (and out of real-time antivirus scanning) shortens it. Ultron keeps the
model loaded for 10 minutes after its last use.

Try “Open Calculator and File Explorer”, “What is my uptime?” or “What can you do?”
See [local file workflows](local-file-workflow.md) for file requests and
[typed commands](typed-command-testing.md) to test without a microphone.

The visual frontend starts separately:

```powershell
npm ci --prefix .\ultron-ui
npm run dev --prefix .\ultron-ui
```

The frontend package supplies the NATS browser client. Open the URL printed by Vite
(usually `http://localhost:5173`). See the [UI guide](../ultron-ui/README.md).

To run components manually, start NATS (`tools\nats\nats-server.exe -c config\nats-server.native.conf`
or `docker compose up -d`), ensure Ollama is running,
then run each in a separate terminal using `.\.venv\Scripts\python.exe`:
`run_ultron.py action_daemon`, `run_ultron.py brain_agent`, `run_ultron.py voice_listener`.

**Stop before restarting:** press Ctrl+C in each component terminal and wait for
shutdown. Stop the UI separately. NATS (native or Docker) and Ollama remain running.
`scripts/windows/stop-ultron-speech.cmd` stops spoken playback, not the whole assistant.

## Checks & diagnostics

```powershell
.\.venv\Scripts\python.exe .\verify_ultron.py
.\scripts/windows/accept-ultron.cmd
```

For a quick typed request while the services are running:

```powershell
.\.venv\Scripts\python.exe .\run_ultron.py send "What is my uptime?" --timeout 5
```

Collect one support ZIP instead of copying terminals:

```powershell
.\scripts/windows/collect-ultron-report.cmd --model qwen3:8b --tests
```

The collector prints the output path under ignored `runtime/`. **Review before
sharing:** bundles include command transcripts, replies and resource names.
Never upload credentials, private email data or personal recordings to an issue.
For a diagnostic JSON without transcript collection, use
`.\.venv\Scripts\python.exe .\run_ultron.py diagnose --model qwen3:8b --tests`.

CI covers portable contracts, Windows brain/acceptance checks and a browser fixture.
Passing tests does not prove live microphone capture, physical speaker output,
current YouTube markup, Google account access or UI performance. `verify_ultron.py
--speech` adds speech-runtime probes; `scripts/windows/accept-ultron.cmd --live-apps` deliberately
opens real applications through a running brain. See [acceptance scope](acceptance.md).


For updated utility commands and optional package installation, see
[Python package layout](python-package.md).
