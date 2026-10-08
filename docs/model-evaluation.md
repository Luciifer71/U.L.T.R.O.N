# Comparing ULTRON's local language models

This is a model-selection experiment, not a model upgrade or production-readiness
certificate. The working brain remains `qwen2.5:7b`. Running the benchmark does
not change `.env`, memory databases, speech settings or tool execution rules.

## What the benchmark does

`model_benchmark.py` uses Python's standard library to contact local Ollama. It
extracts the **current** literal tool definitions and system prompt from
`brain_agent.py` with Python's AST reader. It never imports the brain, loads user
memory, connects to NATS, or executes a proposed tool. An unsupported prompt/schema
construction fails instead of evaluating arbitrary Python.

Fourteen synthetic cases cover application lists, YouTube search, direct/polite
script commands, editor requests, literal extensions, negation, quoted commands,
hypotheticals, missing targets, conversation, stale context and unknown lookup.

The model contract score compares expected tool names and arguments. It ignores
case and redundant whitespace, and allows independent tool order changes. It
preserves punctuation, extensions, extra calls and duplicates. Known acceptable
variants are listed explicitly in `evals/model_cases.json`.

**A contract match is not proof of a correct answer.** For cases requiring no
calls, it establishes only that there was a nonempty answer and no calls. Read
those responses for appropriate clarification, factual quality and false claims.
The unsupported `.py5` case accepts faithful target preservation or clarification;
it does not endorse executing that file type. Execution policy remains separate.

This bypasses ULTRON's deterministic request parser and runtime guards to expose
model differences. It does not reproduce the full live pipeline. For example,
the `Okay, can you run...` parser fix is tested separately in the regression suite.
Do not promote a model based only on this small development set; add held-out
cases and live tests before changing the default.

## 8 October development results and request-fidelity patch

The supplied laptop reports measured Qwen2.5 7B at 27/42 contract passes
(three rounds), Qwen3.5 4B at 6/14, and Qwen3 8B at 10/14 (one round each).
Median model-request times were 0.748, 1.566, and 1.093 seconds respectively.
These are brain-only runs; no combined Whisper performance has been measured.
Qwen3 is a candidate, not a promoted default. It changed `report.py5` to
`report.py`, invented script filenames and omitted a requested document.

The request-fidelity patch shares polite prefixes between app and resource
parsers, preserves punctuation during resource target validation, and clarifies
the prompt and legacy Python tool description. App catalog alias matching stays
separate. This bounded grammar is not a universal natural-language intent proof.
Catalog-backed clarification and arbitrary multi-step completeness remain open.

Because the prompt now includes examples drawn from observed failures, future
scores on these same fourteen cases measure development regressions, not held-out
generalization. Compare unseen filenames and phrasing before promotion. Local
tests use mocked model responses and do not establish improved LLM accuracy.

After installing the reviewed patch, first run `verify_ultron.py`, then compare
the baseline and Qwen3 using the same updated prompt. Separately measure the
candidate with Whisper loaded and transcribing. The `--label` option only labels
reports; it does not load Whisper. Runtime thinking/context controls must match
the benchmark before any live default change. Keep `qwen2.5:7b` as rollback.

## Laptop target and candidates

### Opt-in Qwen3 live trial

Live trial follow-up: Whisper produced `open calculator,` twice. The bounded
app parser now tolerates one terminal comma only when the entire target is one
known application alias. It still requests clarification for `open calculator
and`, repeated commas and dangling multi-app lists. This does not recover lost
audio; the listener must continue rejecting recordings with detected loss.
No change to the audio queue, transcription filter or model warmup is included
in this punctuation correction. The first live run exposed audio overflow and
cold-start delays that remain open before release/default-model promotion.

The revised prompt scored 12/14 for Qwen2.5 and 14/14 for Qwen3 in the supplied
single-round report `20261008T011004504914Z.json`. Manual review confirmed Qwen3
preserved `report.py5` but proposed running it; the resource service must still
reject unsupported script types. Qwen2.5 emitted a script call as plain text
and proposed opening Notion for the hypothetical. No promotion is implied.

After verification, stop all existing ULTRON components and run
`start-qwen3-trial.cmd` from PowerShell. This inherits the normal launcher and
sets process-local `LLM_MODEL=qwen3:8b`, `LLM_THINKING=off`, `LLM_CONTEXT=4096`,
`LLM_TEMPERATURE=0`, and `LLM_SEED=42`. It does not edit `.env`. Runtime controls
apply to initial inference, follow-up requests and retries. Unset controls leave
the existing behavior intact; `LLM_THINKING=default` omits the think parameter.
Only opt into thinking controls for a model that supports them.

Confirm the brain banner names `qwen3:8b` and the listener reports CUDA. Capture
`ollama ps` and `nvidia-smi` while both are loaded. Try fresh conversation and
negative requests (for example, "If I asked you to open Spotify, explain what
you would do, but do not open it"), then a harmless application request. Test
the existing harmless script and editor request, including the polite prefix.
Save transcripts and actual outcomes. These live checks are not part of the
model-only score; throughput and speech quality remain unmeasured until tested.

Rollback: stop all three components, then use `start-ultron.cmd` from a normal
shell. It uses the original `.env`/environment model selection (Qwen2.5 by
default). The trial wrapper uses `setlocal`, so its settings do not persist in
the calling shell. Never start a second trial brain alongside an existing brain.

`LLM_MODEL` is the actual model setting used by both launcher and brain;
the old `OLLAMA_MODEL` example was incorrect and has been corrected.

User-reported hardware: i9-14900HX, RTX 4060 Laptop 8 GB VRAM, 16 GB DDR5 RAM,
1 TB Gen 4 SSD. Free disk space and sustained SSD speed are not yet measured.

- Baseline: `qwen2.5:7b`.
- First candidate: `qwen3.5:4b`.
- Comparison candidate: `qwen3:8b`.

Use explicit tags. The report records installed model digests because tags can
change. Download size is not running VRAM usage. These models can be compared
through Ollama without installing AirLLM or changing the project dependencies.

## Windows: first comparison

1. Stop the brain, action daemon and listener with Ctrl+C. Keep Ollama running.
   Do not launch `start-ultron.cmd` during this initial model-only comparison.
2. In PowerShell at `C:\Users\Krish\Ultron-core`, download the candidates:

```powershell
ollama pull qwen3.5:4b
ollama pull qwen3:8b
```

The baseline must also be installed (`ollama list`). Model downloads can consume
several GB each. If Ollama reports an unsupported architecture, update Ollama
through its normal installer and retry; do not downgrade project packages.

3. Run `ollama ps`. For each listed model, run `ollama stop NAME`, replacing NAME
   with its exact listed tag. A stopped brain may have left its model loaded.
   The benchmark refuses to begin while any Ollama model is loaded, rather than
   silently stopping another application’s model.
4. Run this one command (venv activation is optional):

```powershell
.\.venv\Scripts\python.exe .\model_benchmark.py
```

Defaults: all three models, 14 cases each, three repetitions, 4096 context tokens,
256 maximum generated tokens, temperature 0, seed 42, and thinking disabled for
models advertising thinking support. The baseline receives no unsupported
`think` option. Context limits and thinking settings affect results; the report
records them. Seed/temperature settings do not guarantee bit-identical answers.

Each model gets a separately timed warmup. It stays loaded for its cases and is
then explicitly unloaded before the next model. Do not run other Ollama clients
concurrently: the benchmark is not a server-wide lock.

For a short initial check or baseline-only run:

```powershell
.\.venv\Scripts\python.exe .\model_benchmark.py --models qwen2.5:7b --repeats 1
```

Missing models cause preflight failure; the tool never downloads models itself.
Ctrl+C records a partial report and attempts unloading. A timeout stops the run
rather than queuing more requests. The HTTP timeout is a socket timeout, not a
guaranteed server-side cancellation deadline. Check `ollama ps` after interruption
or an error; `ollama stop NAME` may still be needed.

## Reports and interpretation

Reports are stored in ignored `runtime/benchmarks/` with unique UTC filenames.
Existing output files are never intentionally overwritten. An explicit path can
be passed with `--output`; use a different filename for each run.

Reports include:

- Ollama version, model digests/details, brain-source and fixture hashes.
- Warmup wall time and server-reported model-load time.
- Per-request wall time, tool proposals, answer text, and contract result.
- Server-reported generation throughput; this excludes prompt evaluation and
  load time and is not equivalent to voice response latency.
- Median and nearest-rank p95 request wall time over the small synthetic set.
- An Ollama residency snapshot after the cases. `size_vram` is **model residency**,
  not whole-GPU memory use or peak VRAM. Other applications/Whisper are additional.

Exit 0 means all requested measurements finished, even if a model failed many
cases. Exit 2 means preflight or measurement failed. Exit 130 means interruption.
Never interpret a successful process exit as a model passing the quality gate.

Inspect negative-case responses manually. Compare task correctness before speed.
A larger/newer model is not automatically better at ULTRON's tool contract.

## Concurrent speech follow-up (not part of the first run)

After the brain-only comparison, repeat with the voice listener loaded on CUDA
but the **brain stopped**, and label that run:

```powershell
.\.venv\Scripts\python.exe .\model_benchmark.py --label whisper-loaded
```

The label documents the workload; it does not start or verify Whisper. NATS must
be available for the listener. Confirm its CUDA log and watch GPU memory in Task
Manager or `nvidia-smi`. An idle listener establishes resident-memory competition;
it does not measure simultaneous transcription. A separate controlled audio
replay is needed for that, along with microphone accuracy and end-to-end latency.
Do not compare these runs as if their workloads were identical.

## Promotion and rollback

No automatic promotion is implemented. Review the results, test real tool API
compatibility, preserve negative cases, and validate the speech workload before
changing `LLM_MODEL` in local `.env`. The live runtime does not currently apply all
benchmark options (notably thinking/context); match those settings explicitly in
a reviewed follow-up change before claiming benchmark/live equivalence.

Preserve the old model and record prior settings. Rollback means restoring
`LLM_MODEL=qwen2.5:7b` and restarting the components. Do not delete model weights,
replace `brain_agent.py` wholesale, or disable execution guards to get a higher
benchmark score.

## Automated checks and Git

`verify_ultron.py` discovers `test_model_benchmark.py` automatically. The portable
CI matrix runs its mocked/offline tests without model downloads or GPU access.
These test parsing, scoring, failures and non-execution, not model quality.

Keep benchmark implementation and CI/documentation as reviewable commits. Do not
commit local reports, `.env`, audio, resource indexes or machine-specific data.

Sources: https://docs.ollama.com/api/chat and https://docs.ollama.com/api/ps
