# Typed-command checks

Use typed commands to separate speech recognition from planning and execution.
Start the updated brain and action daemon with the normal trial launcher. The
voice listener may remain running; each typed response is matched by request ID.

From the project directory in PowerShell:

```powershell
.\.venv\Scripts\python.exe .\verify_ultron.py
.\start-qwen3-trial.cmd
```

Wait for component readiness, then use another terminal:

```powershell
.\.venv\Scripts\python.exe .\run_ultron.py send "What is my uptime?"
.\.venv\Scripts\python.exe .\run_ultron.py send "Open the calculator and file explorer for me."
```

These are **live commands**, not a dry run. The second opens applications.
The CLI prints the matched response, task ID and execution status; it exits 0
for a successful response, 1 for a reported execution failure, and 2 for a
transport error or timeout. Use `--timeout 60` for a longer wait. A timeout does
not cancel the task: inspect the brain log before resending to avoid duplicate
actions. An older brain without response correlation will time out.

Compare the typed result with the same spoken request. If typing works but the
transcript differs, investigate recognition. If the exact typed request fails,
investigate planning or execution. Collect both runs with:

```powershell
.\collect-ultron-report.cmd --model qwen3:8b --tests
```

## Conversation and task memory

The brain keeps up to five complete ordinary conversational exchanges during
its current process. Failed action requests, staged plans and tool traces do not
enter that conversational history. Tool evidence is available during its own
request; use runtime status or an explicit fresh information request afterward.

On restart, old mixed chat rows are not replayed into the model. SQLite audit
logs, saved user facts, task records and the explicit replay mechanism remain.
This prevents previous action errors from being supplied as sample answers to
unrelated speech. It does not guarantee that the model will never produce an
irrelevant reply, and it does not correct a misheard transcript automatically.
