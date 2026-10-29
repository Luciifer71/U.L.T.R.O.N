# U.L.T.R.O.N.

Local-first AI assistant. Voice, memory and controlled desktop actions.

**Status: v1 in development.** Windows is the primary integrated runtime. Portable
contract tests run on macOS and Linux; they do not establish full desktop support.
This is a working development project, not a production-ready release or an
unrestricted autonomous agent.

[Setup](#setup--windows) · [Run](#run) · [Checks](#checks--diagnostics) ·
[Technology stack](docs/technology-stack.md) · [Contributing](CONTRIBUTING.md)

## Current capabilities

| Area | Available now | Boundaries |
| --- | --- | --- |
| Voice | Wake with “Hey Ultron”, speak a request, receive a spoken reply | Microphone, recognition and audible output require live testing; sessions return to standby after inactivity |
| Applications | Resolve installed apps, stage actions and report outcomes | OS dispatch and verified completion are distinguished; supported targets depend on the platform |
| Local files | Search an explicitly named folder and open supported files; numbered follow-up choices | Ambiguous results require a choice; bounded ordered workflows stop on failure |
| Local information | Time, date, disk space, system telemetry and scoped runtime status | A status reply is not a full-system health check |
| Google updates | Optional cached email importance counts and primary-calendar updates | Read-only, account consent required; partial archive scans and stale data are reported |
| Web | Open websites and search Google or YouTube | Search results are not playback confirmation |
| YouTube playback | Optional isolated browser selection and playback-state checks | Experimental: live result selection still fails in some cases |
| Memory and knowledge | SQLite facts/task records and ChromaDB document retrieval | Local storage needs care; do not publish personal data |
| Visual interface | React/Three.js particle scene receiving semantic NATS events | Experimental rendering; smooth animation and event responsiveness need live validation |

## Architecture

The listener publishes requests to the brain over NATS. The brain validates and
stages actions, records outcomes and publishes replies. The action daemon handles
speech output; the frontend consumes visual-state events independently.

| Component | Responsibility |
| --- | --- |
| `voice_listener.py`, `audio_pipeline.py`, `microphone_runtime.py` | Capture, speech segmentation, transcription, wake/session handling and input recovery |
| `brain_agent.py`, `ollama_runtime.py` | Deterministic routing, local model planning, readiness/retries and execution orchestration |
| `ultron_control/` | Resource discovery, policy checks, file workflows, Google integration and action verification |
| `memory_db.py`, `ingest.py` | Persistent local memory and knowledge ingestion |
| `action_daemon.py` | Spoken replies and playback lifecycle |
| `ultron-ui/` | Visual entity and NATS WebSocket bridge |
| `gesture.py`, `audio_listen.py` | Separate experimental perception utilities; not part of the normal launcher |

Core subjects: `ultron.intent`, `ultron.visual`, `ultron.voice`.
Local endpoints: NATS `127.0.0.1:4222`, browser WebSocket `127.0.0.1:9222`,
NATS monitoring `127.0.0.1:8222` and Ollama `127.0.0.1:11434`.
Keep the development services local; this is not a hardened public deployment.

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
configurable. See [.env.example](.env.example) for runtime settings and
[model evaluation](docs/model-evaluation.md) for benchmark scope.

For supported NVIDIA speech inference on x64 Windows:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-speech-windows.txt
```

This does not install an NVIDIA driver. Follow the [voice runtime guide](docs/voice-runtime.md)
for CUDA validation, microphone selection and fallback behavior.

### Optional integrations

- **Google:** follow [account setup, privacy and coverage](docs/google-updates.md).
  Installation does not connect an account. Google consent is required; tokens
  use Windows Credential Manager. Access cannot send or delete emails.
- **YouTube playback:** run `setup-youtube-playback.cmd` and read the
  [playback guide](docs/youtube-playback.md). Edge is the default; installed Chrome
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
saying “Hey Ultron”. `start-qwen3-trial.cmd` remains the explicit Qwen3 profile
(thinking off, context 4096, temperature 0, seed 42); it does not rewrite `.env`.

Try “Open Calculator and File Explorer”, “What is my uptime?” or “What can you do?”
See [local file workflows](docs/local-file-workflow.md) for file requests and
[typed commands](docs/typed-command-testing.md) to test without a microphone.

The visual frontend starts separately:

```powershell
npm ci
cd ultron-ui
npm ci
npm run dev
```

The root install supplies the NATS browser client. Open the URL printed by Vite
(usually `http://localhost:5173`). See the [UI guide](ultron-ui/README.md).

To run components manually, start `docker compose up -d`, ensure Ollama is running,
then run each in a separate terminal using `.\.venv\Scripts\python.exe`:
`action_daemon.py`, `brain_agent.py`, `voice_listener.py`.

**Stop before restarting:** press Ctrl+C in each component terminal and wait for
shutdown. Stop the UI separately. Docker and Ollama remain running.
`stop-ultron-speech.cmd` stops spoken playback, not the whole assistant.

## Checks & diagnostics

```powershell
.\.venv\Scripts\python.exe .\verify_ultron.py
.\accept-ultron.cmd
```

For a quick typed request while the services are running:

```powershell
.\.venv\Scripts\python.exe .\send_intent.py "What is my uptime?" --timeout 5
```

Collect one support ZIP instead of copying terminals:

```powershell
.\collect-ultron-report.cmd --model qwen3:8b --tests
```

The collector prints the output path under ignored `runtime/`. **Review before
sharing:** bundles include command transcripts, replies and resource names.
Never upload credentials, private email data or personal recordings to an issue.
For a diagnostic JSON without transcript collection, use
`.\.venv\Scripts\python.exe .\ultron_diagnostics.py --model qwen3:8b --tests`.

CI covers portable contracts, Windows brain/acceptance checks and a browser fixture.
Passing tests does not prove live microphone capture, physical speaker output,
current YouTube markup, Google account access or UI performance. `verify_ultron.py
--speech` adds speech-runtime probes; `accept-ultron.cmd --live-apps` deliberately
opens real applications through a running brain. See [acceptance scope](docs/acceptance.md).

## Before v1

Current reliability priorities:

- Resolve live YouTube result-selection failures and capture useful failure evidence.
- Investigate intermittent audio backlog/queue overload under real workloads.
- Measure UI frame time and visual-event responsiveness; fix the reported regression.
- Keep Google freshness, authorization failures and partial coverage explicit.
- Complete repeatable live acceptance before declaring a usable release.

Future work includes richer orchestration, durable alert delivery and an authenticated
[iPhone companion](docs/iphone-companion-roadmap.md). These are plans, not current
capabilities. There is no release date promised here.

## Documentation

| Guide | Contents |
| --- | --- |
| [Technology stack](docs/technology-stack.md) | Full technology and library inventory, including experimental/optional components |
| [Resource control](docs/resource-control.md) | Discovery, policy and execution contracts |
| [File workflows](docs/local-file-workflow.md) | Scoped search, choices and ordered requests |
| [Voice runtime](docs/voice-runtime.md) | CUDA, microphone behavior and speech diagnostics |
| [Google updates](docs/google-updates.md) | OAuth setup, local cache and read-only limits |
| [YouTube playback](docs/youtube-playback.md) | Setup, browser choice and verification boundaries |
| [Runtime status](docs/runtime-status.md) | Measured telemetry and scoped health answers |
| [Support bundles](docs/support-bundles.md) | Collection, privacy and report contents |
| [Acceptance](docs/acceptance.md) | Automated checks and live release evidence |
| [Development priorities](docs/development-todo.md) | Current work and longer-term ideas |

## Contributions

See [CONTRIBUTING.md](CONTRIBUTING.md) for lightweight test setup, reporting and
contribution requirements. Reproducible issues are welcome. An open-source license
is pending an owner decision; public visibility does not grant reuse rights.

## License & Ownership

**Copyright © 2026. All Rights Reserved.**

This repository and its source code are **proprietary**.

Permission is granted solely to view the code for educational and demonstration purposes.

No part of this software may be reproduced, distributed, modified, or used in commercial applications without explicit prior written consent from the owner.

---

<sub>still building.</sub>
