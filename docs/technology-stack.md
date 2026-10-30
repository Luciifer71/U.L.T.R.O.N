# Technology stack


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
| Speech activity | Silero VAD through Faster-Whisper | Speech segmentation and endpoint detection |
| Google integration | Google API Python client; google-auth, google-auth-oauthlib, google-auth-httplib2; keyring | Optional read-only Gmail/Calendar access and Windows credential storage |
| Browser playback | Playwright | Optional isolated Edge/Chrome browser; player-state verification |
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
complete or production-ready.
Broader browser and desktop automation remain under development.

**Dependency references:** [Python](../requirements.txt),
[Windows GPU speech](../requirements/speech-windows.txt), and
[frontend](../ultron-ui/package.json) contain the declared packages and version constraints.

This overview is provided for technical review. See [License & Ownership](../README.md#license--ownership)
for the project's stated usage restrictions; listing third-party technologies does
not grant permission to reuse Ultron's implementation.


Optional manifests: [Google](../requirements/google.txt), [browser](../requirements/browser.txt) and [tests](../requirements/test.txt). The NATS browser client is declared in the [frontend package manifest](../ultron-ui/package.json).
