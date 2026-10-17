# Acceptance and release scope

Run `accept-ultron.cmd` from a configured Windows checkout, or
`python ultron_acceptance.py`. This runs the full regression suite and thirteen
request/guard checks, records source hashes, timings, test counts and explicit
untested areas, then writes a single `runtime/support/ultron-acceptance-*.zip`.
No live application action is performed by default. GitHub Actions runs this
same command on Windows and saves the ZIP as an artifact.

The deterministic cases include inserted commas, polite app lists, incomplete
lists, negation, quoted commands, search text and the observed garbled transcript
"Annual pull, file explorer, calculator and two things." They are application
contracts, not measurements of speech-recognition accuracy or model intelligence.
Regression tests also assert that every app preflight finishes before any action
starts, and that a missing app prevents the entire batch from executing.

For an explicitly requested live check, use `accept-ultron.cmd --live-apps`
with the updated brain and action daemon already running. It asks for uptime
and opens Calculator and File Explorer, validates matched responses, records
latency, and includes those results in the same ZIP. Offline failures block live
checks. A timeout stops further commands without retrying; it cannot cancel an
already dispatched command. Live checks do not use arbitrary uploaded transcripts.
The regular support collector includes the most recent acceptance JSON with its
timestamp; an old result is evidence of that run only, not the current checkout.

## Application execution contract

Application names alone do not authorize launch. An explicit launch clause must
name each target; unclear, conditional, negated or explanatory requests clarify.
Before a batch starts, all `open_application` targets are resolved using the same
catalog/discovery paths used by execution. Any resolution failure blocks the whole
batch. This is a preparation gate, not an atomic transaction: permissions, files
or processes can change afterward, and runtime failures can still produce partial
execution. Actual execution continues to use existing policy checks and reports
verified vs dispatched outcomes separately.

## Default model

Qwen3:8b is the default local model with thinking off, context 4096, temperature 0
and seed 42. The earlier controlled Windows comparison scored 14/14 planning
contracts for Qwen3 versus 12/14 for Qwen2.5, at similar median latency (~0.81s).
That small single-repeat comparison supports a working default, not a general
reliability guarantee. Fast known commands bypass model inference. Current CI
uses mocked inference and deterministic cases; it does not load a real model.

Existing `.env`/process settings are not overwritten. `LLM_MODEL` selects another
model; absent profile settings use Qwen3 defaults only for `qwen3:8b`. Other models
retain unspecified sampling/thinking settings. Explicit blank context/sampling
values and `LLM_THINKING=default` leave those options to Ollama. The old Qwen3
trial launcher remains available for an explicit pinned profile.

Microphone recognition, speaker audibility, GPU placement and a user's desktop
remain distinct live acceptance areas. Passing this command alone does not certify
release readiness for every machine. No paid API or new cloud service is required.
The project license is unchanged; contributor/public-release licensing is a later
owner decision.
