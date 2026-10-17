# One-file support reports

Use the updated launcher at least once before collecting logs:

```powershell
.\start-qwen3-trial.cmd
```

The launcher now copies Python output from `brain_agent`, `voice_listener`, and
`action_daemon` to `runtime/logs/` while keeping their terminals visible. Each
component retains a rolling log and one backup, approximately 2 MiB each.
Directly running a component's Python file does not enable this capture.
Earlier terminal output cannot be recovered retroactively.

After reproducing a problem, run in a separate project PowerShell terminal:

```powershell
.\collect-ultron-report.cmd --model qwen3:8b
```

To include regression testing as well:

```powershell
.\collect-ultron-report.cmd --model qwen3:8b --tests
```

The command prints the path of one ZIP under `runtime/support/`. Review and upload
that file. Collection works while components are running; stop them first if a
fully settled log snapshot is needed. The collector does not start or stop them.

## Contents and limits

- Recent Python component logs, including captured traceback output and timings.
- A fresh diagnostic JSON report and diagnostic/test console output.
- A manifest identifying missing files, log modification times and truncated tails.

Existing logs may contain multiple sessions; session-start markers distinguish
runs. Missing logs are reported explicitly. Native Ollama/Docker terminal output,
launcher preflight output, and direct native-library writes to file descriptors
are not captured by the Python console copies.

Environment files, SQLite databases, audio recordings and other project files
are not collected. Redaction masks common credential fields, URL tokens and
Windows user-directory names, but is best effort: spoken commands, replies,
filenames and other personal content can remain. Inspect the archive before
sharing. Nothing is uploaded automatically. Runtime logs and bundles stay under
the git-ignored `runtime/` directory.

The diagnostic report also includes the ten largest processes by resident memory
(RSS), with process name, PID and bytes. It excludes command lines, executable
paths and environment variables. Process names can still reveal running apps.
RSS can include shared pages and is not GPU memory; do not sum these rows as an
exact explanation of total RAM usage. Inaccessible or exited processes are skipped.

Audio-discard warnings identify driver status, frame-sequence gaps or application
mailbox overflow where known. The mailbox dropped-frame count is cumulative and
covers only Ultron's queue: zero does not exclude loss reported by the audio driver.
A warning pertains to the affected capture, not necessarily a complete utterance
already submitted for transcription.
