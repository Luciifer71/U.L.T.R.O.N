# General local resource control: implementation checkpoint

This change adds a reusable resource service. It does not establish production
release readiness or port the entire assistant to macOS. Existing voice, NATS,
memory, and known Windows application routes remain available.

## Supported operations

| Request | Windows | macOS | Evidence |
| --- | --- | --- | --- |
| Find a file/folder by name | SQLite metadata catalog | Same catalog | Accessible candidates, no execution |
| Open a document/folder | File association | `/usr/bin/open` | Dispatch accepted, window not verified |
| Open text in an editor | Notepad | TextEdit | Dispatch accepted |
| Launch a native application/game | `.exe`, game directory as cwd | `.app`, Launch Services | PID/dispatch, readiness not verified |
| Execute a script | Python, PowerShell | Python, POSIX shell | Exit status, bounded stdout/stderr, timeout |
| Read a file | Bounded UTF-8 text | Same | Actual contents; binary formats need another adapter |

Python scripts use ULTRON's current Python interpreter. PowerShell uses the
system interpreter without bypassing execution policy. Script timeout defaults
to 30 seconds; the typed service allows at most 120 seconds. GUI games are
launched without waiting for the game to exit.

Scripts receive literal argument lists, never a constructed shell command.
Shell/batch command strings, elevation, installers, Linux GUI opening, arbitrary
editor selection, and browser-specific DOM navigation are not implemented by
this resource service. Unsupported operations return an error.

## Scope and data

Default scope is the user's home plus currently mounted local/removable Windows
drives, or home, `/Applications`, and mounted macOS volumes. Normal OS account
permissions still apply. Indexing stores paths and metadata, not file contents.
It skips Windows system locations, common credential stores, `.env`, symlinks,
and junctions. Targets are checked again at operation time; stale rows are not
execution authorization. Name resolution preserves spelling, Unicode marks and
version numbers while allowing cosmetic spaces/punctuation.

Each user owns a separate catalog/settings directory:

* Windows: `%LOCALAPPDATA%\ULTRON`
* macOS: `~/Library/Application Support/ULTRON`
* Headless Linux tests: `$XDG_DATA_HOME/ultron` or `~/.local/share/ultron`

Optional `resource-settings.json` contains absolute roots and additional
protected locations. `ULTRON_RESOURCE_CONFIG` can select another settings file.
For example, a Windows JSON file can contain:

```json
{
  "roots": ["C:\\Users\\Krish", "G:\\"],
  "protected": ["G:\\Private"]
}
```

This is a discovery/dispatch policy, **not a sandbox for executed code**. A
requested script runs with the account's privileges and can itself read or
modify other locations. Deny lists cannot identify every sensitive file;
hardlinks, filesystem races, hostile file associations, and durable process
containment require further platform work. Do not run ULTRON as administrator
to repair a discovery failure.

## Indexing and typed diagnostics

Run from the checkout using the project interpreter. Full paths work without
indexing. Name-only requests require an index:

```powershell
.\.venv\Scripts\python.exe .\resource_cli.py index --root "G:\"
.\.venv\Scripts\python.exe .\resource_cli.py search "Forza Horizon 6" --root "G:\"
```

Indexing is explicit, bounded to 100,000 entries/30 seconds per root by default.
`complete: false` and exit code 2 mean partial coverage; they are not a passing
full scan. Use a narrower containing folder or explicitly increase
`--max-entries`/`--scan-seconds`. A repeated partial scan does not resume a saved
crawl. Complete refreshes prune stale metadata; partial ones preserve it.
Scanning time limits are checked between filesystem calls and cannot interrupt
a stuck OS read. No watcher or continuously updated global inventory is claimed.

Duplicate exact names require a folder/full path. Search results may be bounded;
execution resolution independently checks exact matches so a truncated search
cannot establish uniqueness. Similar names are never automatically executed.

Typed operations for local diagnosis:

```powershell
.\.venv\Scripts\python.exe .\resource_cli.py open "notes.txt" --editor Notepad
.\.venv\Scripts\python.exe .\resource_cli.py launch "Forza Horizon 6" --root "G:\"
.\.venv\Scripts\python.exe .\resource_cli.py run "sample.py"
```

Use actual unique names from your catalog. `--argument=value` supplies one
literal argument; repeat it for additional values. Do not use a damaged speech
transcript as a filename correction instruction.

## Brain integration and preserved behavior

`find_resources` returns metadata. `operate_resource` stages the requested
operation, and the existing task/execution ledger records its real outcome.
Script exit 0 means completed; nonzero/timeout means failed; opening/launching
does not prove GUI readiness. Script output is bounded to 20,000 bytes per
stream and retained in local task memory, so avoid printing secrets in scripts.

Current-request guards reject unrequested operations, substituted targets,
invented arguments, invented folders, and invented editors. These guards are
deliberately conservative about conditions/negation and may require restating
a complex request. They are not a universal natural-language intent proof.
Resource operations are not silently added to replay plans.

Known Windows applications still use the capability broker when no native
catalog executable matches. Their discovery uses exact installed names and
known aliases, not fuzzy spelling. Microsoft Store has its stable registered
protocol route. Model failure to produce a plan now yields a planning failure,
not an invented assertion about OS permissions.

Existing protocol, process/power, clipboard, folder organization, knowledge
retrieval, and browser automation code still need their own portability and
policy review. The current launcher is Windows-only. The macOS resource adapter
is an implementation foundation, not an assertion that the whole voice/brain/UI
stack is supported there.

## Validation and Git checkpoints

The update installer validates expected file hashes before modifying anything,
backs up old files, and rolls back installed files if replacement fails. It
does not touch `.env`, the venv, recordings, memory databases, or UI sources.
It changes existing source files where necessary; backups preserve their old
contents. An incompatible local version stops installation.

Automated tests cover actual Python execution, nonzero exits, timeouts, bounded
output, ambiguous names, deleted files, scope/protected-path checks, Unicode,
symlink escapes, literal argv, current-request grounding, existing app fallback,
and installer failure/rollback. OS GUI APIs are mocked in contract tests. The
added GitHub workflow checks portable contracts on Windows/macOS/Linux and
brain integration on Windows after the branch is pushed.

Before committing: run `verify_ultron.py --speech` on the Windows workstation,
then check one ordinary document/editor operation, one harmless Python script,
one installed app, and one actual game launch. Confirm duplicate/unknown names
do not launch another file. Native macOS opening/script behavior must also be
validated before advertising macOS support. GPU transcription accuracy remains
a separate evaluation; this change does not correct misheard names.

Commit earlier validated voice/launch work first if still uncommitted. Then
commit this resource service and its guards/tests as a separate coherent change.
Do not stage `.env`, runtime catalogs, recordings, or old patch files.
