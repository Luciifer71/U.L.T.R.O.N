# Runtime status and concise uptime replies

The trial branch supports two read-only information paths:

- `get_system_telemetry`: CPU, memory, battery, plugged-in state and system uptime.
- `get_runtime_status`: responding brain, that brain's NATS connection, and the latest recorded task.

Status results include an observation timestamp and task-update timestamp where
available. The tool excludes its own current request when reading the previous
task. Unavailable task history or unknown connection state is reported explicitly.
A connected brain does not verify the listener, speaker, other subscribers, model
inference availability or the whole operating system.

Single status-tool results are formatted directly from the evidence, without a
second model call. Other wording can be routed to the tool by the local model;
that routing still needs live evaluation. The exact recorded request "Okay, and
are there any errors?" is handled directly without model inference.

"What is my uptime?" returns only uptime, with correct singular/plural units.
"What are my system statistics?" still returns the full telemetry summary.

## Windows acceptance check

Stop existing components before updating. Run:

```powershell
.\.venv\Scripts\python.exe .\ultron_diagnostics.py --model qwen3:8b --tests
.\start-qwen3-trial.cmd
```

Run the launcher only after the regression checks pass. After `STANDBY MODE`,
wake Ultron and try:

1. "What is my uptime?" — expect only the duration.
2. "Okay, and are there any errors?" — expect scoped status, not a global all-clear.
3. "Check whether Ultron has a problem." — exercise model selection of the status tool.
4. "Open Calculator." — confirm application launching still works.

Report the brain responses and whether Calculator appeared. These checks do not
validate local movie playback, window placement or sustained microphone capture.
