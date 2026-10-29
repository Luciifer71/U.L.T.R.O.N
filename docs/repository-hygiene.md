# Repository hygiene

The repository is public. A concise README does not conceal public source or history.
`.env.example` is a deliberately small template with local endpoints and automatic
input/device selection. Put personal overrides in ignored `.env`. No account tokens
belong in either template or source. Git ignore rules do not affect files already tracked.

## Layout

- `tests/`: versioned regression source, recursively discovered by both runners.
- `tools/`: manual bus publisher/subscriber and interactive prompt utilities.
- `docs/`: setup and operational guides.
- `evals/`: versioned model-evaluation fixtures.
- `runtime/`: ignored generated reports and logs.
- `knowledge_base/`: ignored personal ingestion input.

Launchers, runtime components and public diagnostic entry points remain at the root
so existing commands and working-directory assumptions keep working. Moving these
requires a separate packaging migration. Model assets used by experimental gesture
code are also retained until its download/path behavior is migrated.

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
