# Contributing to Ultron

Ultron is a local-first desktop assistant. Keep core workflows usable without
paid APIs. Windows is the primary integrated runtime; portable contract checks
also run on macOS and Linux. Passing those checks does not mean every desktop
feature is available on those platforms.

## Current licensing status

The README currently states proprietary, all-rights-reserved terms. Public source
visibility is not an open-source license. An open-source license and contribution
terms are pending the owner's decision. Obtain owner approval before modifying or
redistributing under the current terms. This guide does not grant new rights.
Issues, reproducible reports and discussion of improvements are welcome.

## Development setup (for authorized contributors)

Use Python 3.12 or 3.13 and an isolated virtual environment. The lightweight test
dependencies do not require Ollama, Docker, a microphone, CUDA or a model download.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.\.venv\Scripts\python.exe .\ultron_acceptance.py
```

On macOS/Linux use `.venv/bin/python` in place of the Windows interpreter path.
The full application has separate runtime dependencies; see the README and
[voice setup](docs/voice-runtime.md). Do not install a full audio/vision stack just
to run unit tests. Existing `.env` values override defaults; never commit them.

## Changes and verification

- Work on a focused branch and explain the user-visible problem in the PR.
- Add regression cases for the behavior being changed, including relevant failure
  cases. Test doubles should never launch real user applications.
- Run `ultron_acceptance.py`. It writes a report ZIP and source hashes under
  ignored `runtime/`. Passing offline tests does not certify live audio or GPU use.
- `--live-apps` is optional and opens actual applications. Do not use it in CI.
- Preserve target names, explicit scope, policy checks and the distinction between
  a plan, an OS dispatch and a verified outcome. Do not claim playback or visible
  success without evidence.
- Do not introduce a paid-service dependency into the default path.

GitHub Actions runs portable checks and Windows acceptance. Wait for checks before
merging. Use the PR template to identify tested behavior and remaining limitations.

## Useful reports

Include the request, expected result, actual result, OS/Python/model versions and
commit if known. The support collector captures transcripts and resource names;
review and redact before attaching anything to a public issue. Never post `.env`,
credentials, private audio or memory databases. Prefer a minimal synthetic example
when reporting a private-file problem.

## Repository layout and private files

Regression source lives in `tests/`; manual bus utilities live in `tools/`.
Keep launchers and documented diagnostic entry points stable. See
[repository hygiene](docs/repository-hygiene.md) for ignore rules and update steps.
