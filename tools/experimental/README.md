# Standalone experiments

These utilities are not started by the normal Ultron launcher. Run them explicitly
from the repository root only when needed, with their optional dependencies installed.

| Utility | Purpose | Side effects |
| --- | --- | --- |
| `gesture.py` | MediaPipe hand tracking | Opens the camera and publishes gesture events; may download the model if missing |
| `audio_listen.py` | Separate clap-detection experiment | Opens a microphone and publishes audio events; not integrated wake-word support |
| `ingest.py` | Local document indexing | Reads personal `knowledge_base/` input, calls Ollama embeddings and writes `chroma_db/` |

```powershell
.\.venv\Scripts\python.exe .\tools\experimental\gesture.py
.\.venv\Scripts\python.exe .\tools\experimental\audio_listen.py
.\.venv\Scripts\python.exe .\tools\experimental\ingest.py
```

Start only the utility you intend to use. Camera/clap experiments require NATS;
ingestion requires Ollama and the configured embedding model. The gesture model
lives in `assets/models/`. Ingestion paths remain anchored to the repository root.
The old root-level script paths no longer exist; normal voice launch commands are
unchanged. Never commit personal ingestion material or captured audio/video.
