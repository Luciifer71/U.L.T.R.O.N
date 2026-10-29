# Regression tests

Test source belongs in Git. Generated output does not.

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe .\verify_ultron.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_verify_ultron.py
```

`pytest.ini` provides the application import path and limits default discovery to
this directory. The verification and acceptance runners discover tests recursively.
CI uses explicit `tests/` paths for its platform-specific subsets.

This first layout keeps tests together rather than assigning mixed unit/integration
files misleading labels. Add subdirectories when a coherent suite needs them;
keep test filenames unique. Live/hardware checks remain optional and explicit.
