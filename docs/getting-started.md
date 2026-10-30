# Getting started

Windows is the primary integrated runtime. Run commands from the repository root
unless a different directory is specified. For authorized use under the
[existing ownership terms](../README.md#license--ownership).

## Setup · Windows


Use Python 3.12 or 3.13, Git, Docker Desktop and Ollama. The optional visual UI also
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

The launcher prepares Docker/NATS and Ollama, warms the model and opens the action
daemon, brain and listener in separate terminals. Wait for `STANDBY MODE` before
saying “Hey Ultron”. `scripts/windows/start-qwen3-trial.cmd` remains the explicit Qwen3 profile
(thinking off, context 4096, temperature 0, seed 42); it does not rewrite `.env`.

Try “Open Calculator and File Explorer”, “What is my uptime?” or “What can you do?”
See [local file workflows](local-file-workflow.md) for file requests and
[typed commands](typed-command-testing.md) to test without a microphone.

The visual frontend starts separately:

```powershell
npm ci
cd ultron-ui
npm ci
npm run dev
```

The root install supplies the NATS browser client. Open the URL printed by Vite
(usually `http://localhost:5173`). See the [UI guide](../ultron-ui/README.md).

To run components manually, start `docker compose up -d`, ensure Ollama is running,
then run each in a separate terminal using `.\.venv\Scripts\python.exe`:
`run_ultron.py action_daemon`, `run_ultron.py brain_agent`, `run_ultron.py voice_listener`.

**Stop before restarting:** press Ctrl+C in each component terminal and wait for
shutdown. Stop the UI separately. Docker and Ollama remain running.
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
