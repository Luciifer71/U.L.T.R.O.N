# 🤖 Ultron-AI — Local-First Event-Driven AI Entity

Ultron-AI is a modular, local-first personal AI system built around **local LLM reasoning, persistent memory, retrieval-augmented knowledge, voice interaction, system automation, and a real-time computational visual interface**.

The project is designed as a decoupled event-driven system so that perception, reasoning, execution, memory, and visualization can evolve independently.

> **Status:** Active development. The architecture is being hardened toward a production-grade, extensible system. Some components and integrations are still under development.

---

## 🧠 What Ultron-AI Is

Ultron-AI combines several subsystems into one event-driven runtime:

- **Brain:** local LLM reasoning and tool routing
- **Voice:** speech recognition and wake-word/session handling
- **Memory:** persistent SQLite facts and conversation history
- **RAG:** ChromaDB-backed local knowledge retrieval
- **Actions:** controlled system/application automation
- **Visual Entity:** React + Three.js/WebGPU/TSL computational visualization
- **Event Bus:** NATS for asynchronous service communication

The intended architecture keeps these responsibilities separated rather than building one monolithic assistant process.

---

## 🏗️ Current Architecture

```text
                         ┌─────────────────────────────┐
                         │          NATS BUS            │
                         │      127.0.0.1:4222         │
                         │   WebSocket: 127.0.0.1:9222 │
                         └──────────────┬──────────────┘
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              │                         │                         │
              ▼                         ▼                         ▼
     ┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
     │   Voice Layer   │       │    Brain Layer  │       │   Visual UI     │
     │ voice_listener  │       │  brain_agent.py │       │   ultron-ui/    │
     │ Faster-Whisper   │       │   OllamaRuntime │       │ React / R3F     │
     └────────┬────────┘       └────────┬────────┘       │ WebGPU / TSL    │
              │                         │                └─────────────────┘
              │                         │
              │                         ├───────────────► SQLite Memory
              │                         │
              │                         ├───────────────► ChromaDB / RAG
              │                         │
              │                         └───────────────► Action Execution
              │
              └─────────────────────────────────────────────────────────────
```

### Core event subjects

```text
ultron.intent   → user intent / task requests
ultron.visual   → semantic visual-state events
ultron.voice    → generated voice-response payloads
```

The visual frontend consumes `ultron.visual` through the NATS WebSocket endpoint.

---

# ⚙️ Core Components

## 🧠 Brain Agent — `brain_agent.py`

The Brain is the central reasoning and orchestration layer.

Current responsibilities include:

- Local LLM inference through Ollama
- Tool/function routing
- Intent processing
- Structured tool-call parsing
- Fallback parsing for raw `<tool_call>` output
- Bounded session conversation context; persistent facts and task audit records
- Personal-memory integration
- Tool/action staging
- Typed action execution lifecycle
- Semantic visual-state publishing through NATS

The current default model is:

```text
qwen3:8b
```

The model can be overridden through the `LLM_MODEL` environment variable.

---

## 🔌 Ollama Runtime — `ollama_runtime.py`

`OllamaRuntime` provides a dedicated runtime layer around the Ollama client.

Current responsibilities:

- Configurable Ollama host
- Configurable model
- Startup health checking
- Wait-until-ready behavior
- Retry handling
- Retry backoff
- Request timeouts
- Recovery from temporary Ollama availability failures

Default endpoint:

```text
http://127.0.0.1:11434
```

The Brain therefore does not depend on Ollama being immediately ready at process startup.

---

## 💾 Persistent Memory — `memory_db.py`

Ultron-AI uses SQLite for persistent local memory.

The memory subsystem supports:

- Stored user facts
- Preferences and other durable context
- Conversation history
- Recent-session context
- Persistent local storage

The Brain distinguishes personal-memory retrieval from project/document knowledge retrieval.

---

## 📚 Knowledge Base / RAG — `ingest.py`

ChromaDB is used for local vector retrieval.

Typical knowledge sources include:

- Project documentation
- Local reference material
- Technical notes
- Manuals
- Workspace-specific information

Local vector storage:

```text
chroma_db/
```

Knowledge sources:

```text
knowledge_base/
```

The knowledge base is intended for static or semi-static information, while personal facts belong in SQLite memory.

---

## 🎙️ Voice Perception — `voice_listener.py`

The voice layer provides the speech-to-intent gateway.

Current flow:

```text
Microphone
    ↓
Audio capture
    ↓
Voice activity / filtering
    ↓
Faster-Whisper
    ↓
Wake-word / session handling
    ↓
NATS
    ↓
Brain Agent
```

Current implementation supports a wake-word/session interaction model around:

```text
Hey Ultron
```

The speech engine validates CUDA with an isolated inference probe. Set
`WHISPER_DEVICE=cuda` to require GPU inference, or `auto` to allow an explicitly
logged CPU fallback that preserves the selected model. See
[speech runtime setup and acceptance](docs/voice-runtime.md) for Windows CUDA
dependencies, microphone diagnostics, model evaluation and release checks.

---

## 👁️ Vision / Gesture Perception — `gesture.py`

The perception layer provides computer-vision based gesture processing.

Current technologies include:

- MediaPipe
- OpenCV
- 3D hand landmarks
- Geometric gesture analysis

The vision layer is treated as an independent sensory input node.

---

## ⚡ Action Execution

The Brain uses a typed `PendingAction` lifecycle to represent physical actions before they are executed.

Current lifecycle:

```text
Intent
  ↓
Reasoning / Planning
  ↓
Action Staging
  ↓
EXECUTING
  ↓
Run all queued actions
  ↓
Collect failures
  ↓
Success → IDLE
Failure → ALERT → IDLE
```

The execution lifecycle is intentionally designed so that one failed independent action does not automatically prevent the remaining queued actions from being attempted.

### Current execution semantics

- Actions are explicitly staged before dispatch.
- Actions have a completion policy.
- Process-backed actions receive an execution acknowledgement window.
- The execution state has a minimum visual dwell period.
- Failures are collected and reported.
- Terminal visual states are emitted centrally.

### Current work in progress

The next execution-hardening stage is an **Application Resolver / Registry** that will replace direct dependence on raw LLM-provided application names.

The intended model is:

```text
User request
    ↓
LLM tool call
    ↓
Application Resolver
    ↓
Validated application identity
    ↓
Known launch mechanism
    ↓
Execution + verification
```

This will provide safer and more reliable handling for targets such as Calculator, Edge, Notion, Task Manager, File Explorer, and other installed applications.

---

# 🎨 Visual Computational Entity

The frontend lives in:

```text
ultron-ui/
```

It is built around:

- React
- TypeScript
- React Three Fiber
- Three.js
- WebGPU
- Three.js Shading Language (TSL)

The visual entity is driven by semantic ULTRON states rather than UI buttons alone.

### Current semantic states

```text
offline
starting
idle
listening
thinking
executing
alert
focus
sleep
```

### Visual language

```text
IDLE       → predominantly RED
LISTENING  → BLUE
THINKING   → RED + BLUE / transitional PURPLE
EXECUTING  → GOLDEN YELLOW
ALERT      → RED + GOLD
```

The entity uses continuously evolving fields, particles, information flow, energy events, and a procedural central core.

The frontend receives real-time semantic events over:

```text
NATS WebSocket
ws://127.0.0.1:9222
```

---

# 📨 NATS Event-Driven Mesh

NATS is the shared communication layer between ULTRON services.

Local client endpoint:

```text
nats://127.0.0.1:4222
```

Browser WebSocket endpoint:

```text
ws://127.0.0.1:9222
```

Monitoring endpoint:

```text
http://127.0.0.1:8222
```

The current development deployment keeps these services local to the machine.

The event-driven model allows services to communicate through subjects rather than direct process-to-process dependencies.

---

# 🐳 Infrastructure

NATS is currently deployed through Docker.

Start the infrastructure:

```powershell
docker compose up -d
```

Verify:

```powershell
docker ps
```

Expected local ports:

```text
127.0.0.1:4222  → NATS client connections
127.0.0.1:8222  → NATS monitoring
127.0.0.1:9222  → NATS WebSocket
```

> The NATS development configuration is intended for local development. Production deployment will require appropriate authentication, authorization, TLS, and network restrictions.

---

# 🚀 Setup

## 1. Prerequisites

Install:

- Python 3.11+
- Docker Desktop
- Ollama
- Git
- Node.js / npm for the `ultron-ui` frontend

---

## 2. Clone

```powershell
git clone https://github.com/Luciifer71/U.L.T.R.O.N.git Ultron-core
cd Ultron-core
```

---

## 3. Python Environment

Create the local virtual environment:

```powershell
python -m venv .venv
```

Activate:

```powershell
.\.venv\Scripts\Activate.ps1
```

Command Prompt:

```cmd
.\.venv\Scripts\activate.bat
```

Git Bash:

```bash
source .venv/Scripts/activate
```

---

## 4. Install Python Dependencies

```powershell
python -m pip install -r requirements.txt
```

Additional runtime packages used by the current Brain implementation:

```powershell
python -m pip install keyboard psutil pyperclip duckduckgo-search
```

---

### Windows CUDA speech dependencies

For NVIDIA GPU speech recognition on x64 Windows, install the speech requirements
into the same environment used by the listener:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-speech-windows.txt
```

This does not install or update the NVIDIA driver. Follow the
[speech runtime guide](docs/voice-runtime.md) for CUDA validation and microphone checks.

---

## 5. Configure Environment Variables

Create the local environment file:

```powershell
Copy-Item .env.example .env
```

The `.env` file is local configuration and should not be committed.

Relevant runtime variables include:

```text
NATS_URL
OLLAMA_HOST
LLM_MODEL
ULTRON_EXECUTION_MIN_HOLD_SEC
ULTRON_EXECUTION_ACTION_ACK_SEC
```

Current defaults:

```text
NATS_URL = nats://127.0.0.1:4222
OLLAMA_HOST = http://127.0.0.1:11434
LLM_MODEL = qwen3:8b
ULTRON_EXECUTION_MIN_HOLD_SEC = 1.20
ULTRON_EXECUTION_ACTION_ACK_SEC = 0.20
```

---

## 6. Ollama

Ensure Ollama is installed and running.

Check available models:

```powershell
ollama list
```

Pull the default model when needed:

```powershell
ollama pull qwen3:8b
```

The Brain performs a runtime readiness check before accepting intent processing.

---

# ▶️ Running Ultron-AI

### Windows launcher

After completing setup, run from the repository root:

```powershell
.\start-ultron.cmd
```

The launcher prepares Docker/NATS and Ollama, then opens the action daemon,
brain, and voice listener in separate terminals. Check each terminal for
readiness; wait for `STANDBY MODE` before speaking. The visual frontend is
started separately using the instructions below.

Run the PowerShell commands below from the repository root unless a different
directory is specified. The Python commands use the project’s `.venv` interpreter.

## Terminal 1 — NATS Infrastructure

```powershell
docker compose up -d
```

## Terminal 2 — Brain

```powershell
.\.venv\Scripts\python.exe .\brain_agent.py
```

## Terminal 3 — Voice Listener

```powershell
.\.venv\Scripts\python.exe .\voice_listener.py
```

Wait for microphone calibration to finish and `STANDBY MODE` to appear before
saying **“Hey Ultron”** and giving your command.

## Terminal 4 — Voice Output

```powershell
.\.venv\Scripts\python.exe .\action_daemon.py
```

This component handles spoken replies. Start it before giving voice commands.

## Terminal 5 — Frontend

From the UI directory:

```powershell
cd ultron-ui
npm install
npm run dev
```

The development frontend is typically available at:

```text
http://localhost:5173
```

Additional perception, messaging, ingestion, and development utilities can be started independently as required.

### Stop or restart

Press **Ctrl+C** in each component terminal and wait for shutdown to finish.
Stop the frontend separately in its terminal if it is running. Stop existing
components before restarting or switching launch configurations.

Docker and Ollama remain running after the launcher’s component windows stop.


---

# 🧪 Current Development Status

### Run regression checks

```powershell
.\.venv\Scripts\python.exe .\verify_ultron.py
```

To also probe the configured speech runtime and microphone inventory:

```powershell
.\.venv\Scripts\python.exe .\verify_ultron.py --speech
```

Passing automated checks does not prove live microphone recognition, audible
speech, or successful desktop actions. Validate those separately on your machine.

## Implemented

- Local Python virtual environment
- Ollama-based Brain Agent
- Dedicated Ollama runtime with health/retry handling
- SQLite persistent memory
- ChromaDB RAG infrastructure
- NATS event-driven messaging
- NATS WebSocket visual bridge
- Voice perception and wake-word/session flow
- Gesture perception
- Typed action execution lifecycle
- Multi-action execution with failure collection
- Deterministic `executing → idle` lifecycle
- Deterministic `executing → alert → idle` failure lifecycle
- React / React Three Fiber visual entity
- WebGPU / TSL-based visual systems
- Semantic visual states driven by NATS events

## In Progress

- Application Resolver / Registry
- Verified application launching
- Safer process and system-action policies
- Browser automation
- Improved action-result verification
- Whisper GPU/CUDA runtime optimization
- Ollama resource cleanup and shutdown hardening
- `duckduckgo_search` → `ddgs` migration
- More robust memory/context management
- Expanded tool ecosystem
- Stronger observability and diagnostics

## Planned

- Scheduler engine
- Mobile / iPhone gateway
- Additional multimodal perception
- Expanded automation capabilities
- More sophisticated task orchestration
- Production deployment architecture
- Stronger security and permission controls
- Model benchmarking and runtime selection

---

# 🧭 Development Roadmap

The project is being developed in layers rather than treating every feature as one large implementation.

```text
Foundation
    ↓
NATS Event Mesh
    ↓
Brain + Ollama Runtime
    ↓
Persistent Memory + RAG
    ↓
Voice / Vision Perception
    ↓
Typed Action Execution
    ↓
Application Resolver
    ↓
Action Verification
    ↓
Browser / System Automation
    ↓
Security + Policy Layer
    ↓
Observability / Reliability
    ↓
Production Deployment
```

The goal is to keep each layer independently testable and replaceable.

---

# 🧩 Project Structure

```text
Ultron-core/
│
├── .venv/                      # Local Python virtual environment
├── .vscode/                    # VS Code workspace configuration
│
├── ultron-ui/                  # React / R3F / WebGPU frontend
│
├── chroma_db/                  # ChromaDB vector storage
├── knowledge_base/             # RAG knowledge sources
├── nats_data/                  # Local NATS-related data
│
├── brain_agent.py              # Central reasoning/orchestration engine
├── ollama_runtime.py           # Ollama health/retry runtime layer
├── visual_events.py            # Canonical visual event publisher
├── memory_db.py                # SQLite memory subsystem
├── ingest.py                   # Knowledge ingestion
│
├── voice_listener.py           # Voice interaction gateway
├── gesture.py                  # Vision / gesture perception
├── audio_listen.py             # Audio event detection
│
├── action_daemon.py            # Legacy / auxiliary action service
├── mesh_pub.py                 # NATS publisher utility
├── mesh_sub.py                 # NATS subscriber utility
├── send_intent.py              # Intent publisher utility
├── send_prompt.py              # Prompt interface
│
├── docker-compose.yml          # Local infrastructure
├── requirements.txt            # Python dependencies
├── .env.example                # Environment template
├── .gitignore
└── README.md
```

---

# 🧱 Development Principles

Ultron-AI is being developed around these principles:

- **Local-first AI**
- **Event-driven communication**
- **Modular services**
- **Persistent memory**
- **Retrieval-augmented reasoning**
- **Explicit execution lifecycles**
- **Fault isolation**
- **Typed interfaces**
- **Validated external actions**
- **Observable system behavior**
- **Security-aware automation**
- **Replaceable model/runtime layers**

Future integrations are expected to connect through the same core event architecture.

```text
Ultron Core
     │
     ├── Voice Gateway
     ├── Vision Gateway
     ├── Visual Entity
     ├── Memory / RAG
     ├── Scheduler Engine
     ├── Automation Layer
     ├── Mobile Gateway
     └── External Service Integrations
```

These represent the architectural direction of the project; not every component in this diagram is currently implemented.

---

# 🛠️ Technology Stack

Ultron combines local AI reasoning, voice interaction, persistent memory, controlled
computer actions, and an event-driven visual interface. The overview below preserves
the core technologies and names the supporting libraries without describing internal
prompts or implementation algorithms.

| Layer | Technologies / libraries | Role |
|---|---|---|
| Primary language | Python | Backend components, task orchestration, and system integration |
| Local LLM runtime | Ollama; `ollama` Python client | Local model inference and tool-call planning |
| Default model | Qwen3:8b | Local planner; thinking off, context 4096, temperature 0, seed 42 |
| Model evaluation | Offline-action Ollama benchmark | Compare configurable local models without executing proposed tools |
| Event bus | NATS; `nats-py` | Asynchronous communication between components |
| Browser event transport | NATS WebSocket | Delivers visual-state events to the frontend |
| Relational memory | SQLite; Python `sqlite3` | Persistent facts, conversation history, and task records |
| Vector database / RAG | ChromaDB; `chromadb` | Retrieval from indexed local knowledge |
| Speech recognition | Faster-Whisper; `faster-whisper`, `ctranslate2` | Converts captured speech into text |
| Microphone capture | `sounddevice` | Microphone input for the voice listener |
| Audio processing | NumPy; SciPy | Audio arrays and signal-processing support |
| GPU speech acceleration | NVIDIA CUDA; `nvidia-cublas-cu12`, `nvidia-cudnn-cu12` | GPU speech inference on supported Windows systems |
| Spoken replies | `edge-tts`; `pygame` | Speech generation and audio playback |
| Vision / gestures | MediaPipe; `opencv-python` | Camera-based perception and hand-gesture processing |
| System telemetry | `psutil` | Operating-system resource measurements |
| Computer automation | Python system APIs; `keyboard`, `ctypes`, `subprocess`, `pathlib` | Keyboard integration, native Windows calls, processes, and resource paths |
| Clipboard integration | Optional `pyperclip` | Clipboard access when installed |
| Web lookup | Optional `duckduckgo_search` / DDGS | Search integration; distinct from browser automation |
| Configuration | `python-dotenv` | Loads local environment configuration |
| Async runtime | Python `asyncio` | Coordinates asynchronous component work |
| Supporting declared dependencies | `pydantic`, `requests`, `aiosqlite`, `pyttsx3` | Listed in the Python manifest; not all are active in every runtime path |
| Frontend | React; React DOM; TypeScript | Visual interface and typed frontend code |
| 3D / rendering | Three.js; React Three Fiber | Scene rendering and React integration |
| Visual helpers / effects | Drei; React Three Postprocessing | Scene utilities and visual effects |
| GPU visualization | WebGPU; Three.js Shading Language (TSL) | GPU rendering and procedural shader work |
| Frontend build / lint | Vite; React Vite plugin; Oxlint; TypeScript type packages | Development server, builds, static typing, and linting |
| Infrastructure | Docker; Docker Compose | Local NATS deployment |
| Development | VS Code; Git; Node.js; npm | Editing, version control, and frontend dependency management |
| Testing / CI | pytest; verification scripts; GitHub Actions | Regression checks and automated validation |

**Scope:** This is a technology inventory, not a claim that every integration is
complete or production-ready. Trial-branch work is identified separately.
Broader browser and desktop automation remain under development.

**Dependency references:** [Python](requirements.txt),
[Windows GPU speech](requirements-speech-windows.txt), and
[frontend](ultron-ui/package.json) contain the declared packages and version constraints.

This overview is provided for technical review. See **License & Ownership** below
for the project's stated usage restrictions; listing third-party technologies does
not grant permission to reuse Ultron's implementation.

---

# 🔐 License & Ownership

**Copyright © 2026. All Rights Reserved.**

This repository and its source code are **proprietary**.

Permission is granted solely to view the code for educational and demonstration purposes.

No part of this software may be reproduced, distributed, modified, or used in commercial applications without explicit prior written consent from the owner.

### One diagnostic report (no paid APIs)

With the normal services running, check the configured Qwen3 model and regression suite:

```powershell
.\.venv\Scripts\python.exe .\ultron_diagnostics.py --model qwen3:8b --tests
```

The report is saved under `runtime/diagnostics/`. It includes dependency versions,
CPU/RAM/battery/uptime readings, local Ollama model inventory, the NATS greeting,
and regression status. Omit `--tests` for a quick read-only report. Without
`--model`, the command uses `LLM_MODEL` from the environment or `.env`.
It does not start services, load models, record audio, or launch applications.
Service reachability does not prove that brain/listener/daemon subscribers are
healthy. Missing readings and untested microphone/speaker/desktop checks remain
explicit. The report excludes environment dumps, credentials, transcripts, and
raw test output. Exit status reports regression failure; inspect service statuses
in the report separately.

Ask "What is my uptime?" or "What are my system statistics?" for measured local
readings. Battery percentage and plugged-in status are reported separately.
"Okay, are there any errors?" reports the latest recorded task and explicitly
states that a full system health check has not been performed.


### Automated acceptance

Run `accept-ultron.cmd` for regression tests, deterministic request checks and a
single support ZIP. It does not launch applications or certify microphone audio.
GitHub Actions runs this acceptance suite on Windows and stores the ZIP as a
workflow artifact. Optional `accept-ultron.cmd --live-apps` checks the running
brain and opens Calculator and File Explorer after offline checks pass.

See [acceptance and release scope](docs/acceptance.md). Qwen3:8b is now the
configurable default; existing `.env` and process overrides are respected.
The earlier `start-qwen3-trial.cmd` remains a compatible explicit Qwen3 profile.


### Scoped local files

Say “Play the movie Supergirl from my Downloads folder” or “Open report.pdf from
my Documents folder.” Ultron searches the named folder and opens a unique supported
file through its OS association. Ambiguous, missing or incomplete searches stop
before dispatch. See [supported file workflows and limits](docs/local-file-workflow.md).

### Development and contributions

See [CONTRIBUTING.md](CONTRIBUTING.md) for lightweight test setup, verification and
reporting guidance. Issue and PR templates are available. Open-source licensing
is pending an owner decision; the current ownership terms remain unchanged.

### Follow-up choices and ordered requests

Scoped file requests can offer numbered choices: reply “open the second one”
within 60 seconds. Choices expire after one subsequent request. For a bounded
workflow, say “open Calculator, then play Supergirl from Downloads.” Up to five
explicit app/file actions are preflighted together and run in order; later steps
stop if one fails. See [file workflow details](docs/local-file-workflow.md).
Uncertain speech is rejected as a whole and prompts a repeat during an active
session; this does not guarantee recognition of every spoken title.

### Local assistant facts

Ask “what time is it?”, “what is today's date?”, “how much disk space is free?”
or “what can you do?” for a direct local answer without model inference. Clock
answers use the computer's configured timezone; disk space covers the volume
containing your home folder. These commands do not connect email, calendars or
reminders. See the [my-jarvis review and adopted ideas](docs/my-jarvis-review.md)
for the comparison that motivated this addition.

### Optional Google email and calendar updates

Read-only Gmail scanning and primary-calendar updates can run in the background
while Ultron is open. One-time Google consent is required; accounts are not connected
automatically by installation. Uses optional Google API/auth libraries and Windows
Credential Manager via keyring, without a paid model API. See
[setup, privacy and coverage limits](docs/google-updates.md) and the
[development to-do list](docs/development-todo.md).

Optional [YouTube playback](docs/youtube-playback.md) can select a matching video
and verify browser playback separately from website search. Run
`setup-youtube-playback.cmd` once; it uses installed Microsoft Edge with a separate
Ultron profile. See the guide for consent, autoplay and verification limits.
