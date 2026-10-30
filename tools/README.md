# Developer utilities

Run from the repository root using the project interpreter:

```powershell
.\.venv\Scripts\python.exe .\tools\mesh_pub.py
.\.venv\Scripts\python.exe .\tools\mesh_sub.py
.\.venv\Scripts\python.exe .\tools\send_prompt.py
```

These are manual bus/interactive utilities, not part of the standard launcher.
`mesh_pub.py` sends a sample event; `mesh_sub.py` prints bus traffic, which may
include private requests. `send_prompt.py` dispatches typed requests without the
request/reply timeout reporting of the preferred root `run_ultron.py send` command.
Keep their captured output private unless reviewed and redacted.
