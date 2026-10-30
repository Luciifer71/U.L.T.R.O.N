# Python package layout

Application code is in `src/ultron/`. Normal startup, verification and report
collection wrappers remain at the repository root. No dependency reinstall is
needed for existing checkout users; the root dispatcher adds `src` for itself
and its child probes.

Run from the repository root:

```powershell
.\start-qwen3-trial.cmd
.\.venv\Scripts\python.exe .\verify_ultron.py
.\collect-ultron-report.cmd --model qwen3:8b --tests
```

Other utilities now use the dispatcher:

| Previous Python script | Replacement command |
| --- | --- |
| `google_connect.py doctor` | `python run_ultron.py google doctor` |
| `send_intent.py "hello"` | `python run_ultron.py send "hello"` |
| `resource_cli.py` | `python run_ultron.py resources` |
| `model_benchmark.py` | `python run_ultron.py benchmark` |
| `speech_diagnostics.py` | `python run_ultron.py speech` |
| `ultron_diagnostics.py` | `python run_ultron.py diagnose` |
| `ultron_acceptance.py` | `python run_ultron.py accept` |
| `collect_ultron_report.py` | `python run_ultron.py report` |
| `start_ultron.py` | `python run_ultron.py start` |

Use your `.venv\Scripts\python.exe` interpreter in place of `python` when the
virtual environment is not activated. Remaining arguments pass through unchanged.
Standalone components are `run_ultron.py brain_agent`, `action_daemon` and
`voice_listener`; prefer the normal launcher for environment loading and log capture.
The setup, acceptance and speech-stop batch helpers are under `scripts/windows/`.

## Existing local data

`.env`, `ultron_memory.db`, `chroma_db/`, `nats_data/`, `knowledge_base/` and
`runtime/` stay in their original checkout locations. Per-user Google authorization
and resource databases retain their existing paths. Do not move them into `src`.
Stop running components before pulling the migration, then verify and restart.
Empty folders created earlier are harmless; Git fills them with the tracked files.
Local code importing the old module names must use the corresponding
`ultron.agents`, `ultron.audio`, `ultron.core`, `ultron.cli`, `ultron.control` or
`ultron.resources` module instead.

## Optional development install

```powershell
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

This installs the package and `ultron` console command, not heavy runtime extras.
Install the documented requirement sets separately. A wheel installs Python code
only, not a complete standalone application: configuration, evaluation fixtures,
Docker and the UI still belong to the checkout. When using a wheel, set
`ULTRON_PROJECT_ROOT` to that checkout. Do not set it to a new empty directory.
Root Node manifests remain because the UI currently resolves NATS from the parent
installation; frontend dependency consolidation is separate from this migration.
