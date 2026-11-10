# OpenJarvis review and adoption plan

Reviewed 10 November 2026: [open-jarvis/OpenJarvis](https://github.com/open-jarvis/OpenJarvis)
at commit `68d4290663984508db94a6a59ade45c2b17859ed` (Apache License 2.0, Stanford
Hazy Research / Scaling Intelligence Lab). This is a source-code review, not a
benchmark of either project.

OpenJarvis is a general framework for local-first personal AI: about 1,400 Python
files plus a Rust core and a desktop app, eight agent types, about 40 data
connectors, 35 messaging channels, a skills catalog, an MCP client, research
evaluations and a learning loop over usage traces. ULTRON is a single voice-first
assistant with verified desktop actions. Most of OpenJarvis's breadth does not
fit ULTRON, but the ideas below do.

**Licensing approach:** ULTRON implements these ideas independently. No OpenJarvis
source, assets or data is copied. If code is ever copied, its Apache 2.0 license
text and copyright notice must be kept with it. ULTRON's own ownership terms are
unchanged; a future open-source release would be a separate decision.

## Adopt (planned order, after Phase D camera presence)

| Phase | Idea | OpenJarvis source | What ULTRON gains | ULTRON-specific constraints |
| --- | --- | --- | --- | --- |
| E | Automatic long-term memory | `memory/extractor.py`, `memory/service.py` | After each exchange a small local model extracts lasting facts on a background thread; failures degrade to "no facts" | Facts reviewable and deletable by the user; never store email bodies or secrets; extraction never blocks or fails a task |
| E | Scheduler and reminders | `scheduler/` | One-off, interval and cron tasks: "remind me at 6", daily routines | Scheduled actions go through the same preflight, policy and execution ledger as spoken ones; visible and cancellable in the Ops panel |
| F | Proactive agent with approval tiers | `agents/proactive_agent.py`, `tools/approval_store.py` | Reviews new email and calendar items, proposes actions; trivial ones auto-approve; remembered "always / never" decisions per action pattern | Read-only Google scopes stay read-only; anything with side effects needs approval unless the user set a rule; every decision audited |
| F | Spoken morning briefing | `agents/morning_digest.py`, `connectors/news_rss.py`, `connectors/weather.py` | One spoken summary of mail, calendar, news and weather | Reuse ULTRON's Google sync; RSS fetches pinned to public addresses (no local-network fetches); feed text is untrusted data; prefer a keyless weather source |
| F | Prompt-injection scanning, taint tracking, loop guard | `security/injection_scanner.py`, `security/taint.py`, `agents/loop_guard.py` | Text from email, web or phone that tries to instruct the AI is flagged; untrusted text cannot flow into actions; repeated tool loops are stopped | Required before proactive reading and phone commands go live |
| G | Phone channel (Telegram bot) | `channels/telegram.py` | Free two-way phone link: alerts, commands, approve/deny buttons | Paired, revocable, allow-listed chat only; commands enter the normal intent pipeline; no unauthenticated desktop control (see `iphone-companion-roadmap.md`) |
| H | Local voice (Kokoro TTS) | `speech/kokoro_tts.py` | Removes the online Edge TTS dependency; a custom deeper voice; real audio amplitude for the entity's speaking pulse | Optional; Edge TTS remains the fallback |
| I | MCP tool plugins | `mcp/client.py` | Access to standard tool servers (files, GitHub, home automation) | Allow-listed servers and tools only; every call through the capability broker, preflight and audit |

Later candidates: task analytics in the Ops panel (`traces/analyzer.py`: failure
rates per command and tool) and browser control via the accessibility tree
(`tools/browser_axtree.py`) for more general, more reliable web automation.

## Deliberately not adopted

- **AI-written code or shell execution** (`tools/shell_exec.py`, `code_interpreter*.py`):
  contrary to ULTRON's verified-action design.
- **Bulk community skill import** (thousands of third-party skills): supply-chain and
  injection risk. Any skill must be reviewed individually.
- **35 messaging channels, cloud engine routing, research evaluations, training loop,
  Rust core:** cost and complexity far beyond the benefit, and cloud models break the
  zero-API-budget rule.

## Principle

The goal is an assistant that feels all-knowing: it remembers, anticipates, watches
the user's information, reaches them anywhere and speaks in its own voice. Control
never weakens: approvals, the Stop control, the execution ledger and audit apply to
every new capability. "Godly" here means presence and capability, not autonomy
without oversight.
