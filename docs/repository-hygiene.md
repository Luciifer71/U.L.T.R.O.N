# Repository hygiene

The repository is public. A concise README does not conceal public source or history.
`.env.example` is a deliberately small template with local endpoints and automatic
input/device selection. Put personal overrides in ignored `.env`. No account tokens
belong in either template or source. Git ignore rules do not affect files already tracked.

## Layout

- `tests/`: versioned regression source, recursively discovered by both runners.
- `tools/`: manual bus publisher/subscriber and interactive prompt utilities.
- `tools/experimental/`: standalone gesture, clap and knowledge-ingestion utilities.
- `requirements/`: optional Python dependency manifests; the base `requirements.txt` stays at root.
- `config/`: NATS configuration used by the root Docker Compose file.
- `assets/models/`: the existing hand-landmark model.
- `docs/`: setup and operational guides.
- `evals/`: versioned model-evaluation fixtures.
- `runtime/`: ignored generated reports and logs.
- `knowledge_base/`: ignored personal ingestion input.

Runtime code lives in `src/ultron/`, grouped into agents, audio, core, CLI,
control and resources. `run_ultron.py` dispatches utilities from a checkout;
`verify_ultron.py` and the normal startup/report batch files remain root wrappers.
Secondary Windows helpers live under `scripts/windows/`.
Settings, SQLite memory, Google credentials, NATS data and generated logs retain
their previous locations. No personal data migration is performed.

The legacy local
`test_long_action.py` is ignored explicitly; move it to `runtime/local-tests/`
if you want a clean local root without deleting it.

## Updating an existing checkout

The test and utility moves are already committed. Do not manually move them again.
Before pulling, copy any personal `knowledge_base/` contents to a location outside
the repository: a previously tracked note is removed by this cleanup. Restore your
own notes into the ignored directory afterwards if needed. Do not restore them to Git.
If `git pull` reports local edits, preserve those edits before resolving the update.

```powershell
git status --short
git pull --ff-only origin main
.\.venv\Scripts\python.exe .\verify_ultron.py
```

Review the staging area before each push:

```powershell
git diff --cached --name-only
git ls-files -- .env '.env.*' '*credentials*.json' '*token*.json' 'client_secret*.json'
git check-ignore -v .env .env.local
```

The expected environment-template result is `.env.example`, not a real `.env`.
Inspect suspicious tracked files locally; do not paste credentials into issues or chat.
A pattern scan is not proof of absence. If a real secret was committed, revoke or
rotate it first. Removing the file today does not erase past commits or copies.
History rewriting is a separate coordinated operation, not part of ordinary cleanup.
