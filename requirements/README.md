# Optional dependency sets

The standard runtime manifest remains at `../requirements.txt`.
Run pip from the repository root using the project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements/test.txt
```

| File | Install when |
| --- | --- |
| `test.txt` | Running hardware-free regression and acceptance checks |
| `google.txt` | Enabling optional read-only Google integration |
| `search.txt` | Enabling current optional general web search (`ddgs`) |
| `browser.txt` | Enabling experimental managed YouTube playback |
| `speech-windows.txt` | Setting up supported NVIDIA speech inference on Windows |

Install only the needed sets. This directory holds version constraints, not secrets.
