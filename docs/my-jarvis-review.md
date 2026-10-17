# my-jarvis comparison and adopted ideas

Reviewed 17 October 2026: [harsh-raj00/my-jarvis](https://github.com/harsh-raj00/my-jarvis)
at commit `7386427d8e6096607fa66ca4c71677e3afd0c2b7`.
Ultron baseline: `ed5d2bc`. This is a source-code review, not a side-by-side
hardware benchmark, security audit or certification of either live deployment.

| Area | my-jarvis evidence | Ultron baseline | Assessment |
| --- | --- | --- | --- |
| User interface | React landing page and dashboard with typed chat, microphone, speech stop control and periodic metrics fetches | React/Three.js/WebGPU visual entity and NATS visual-state bridge | my-jarvis has a more complete assistant dashboard flow; visual performance was not tested |
| Model | Gemini API with limited canned fallback without a key; each generation starts chat with empty history | Local Ollama Qwen3:8B, bounded dialogue history and deterministic command paths | Ultron better fits the zero-API-budget local-control goal; no same-task model comparison performed |
| Speech | Browser SpeechRecognition and speechSynthesis in active dashboard | Local Faster-Whisper with capture/loss handling; Edge TTS output | Different tradeoffs; no recognition accuracy winner without common recordings; Ultron's speech output still uses an online service |
| Desktop actions | Reviewed system plugin reports psutil metrics; reviewed chat path returns text rather than validated desktop execution plans | Capability broker, preflight, execution ledger, app discovery and scoped files | Stronger implemented desktop-action evidence in Ultron |
| Plugins | Auto-discovered BasePlugin subclasses with priorities and lifecycle hooks | Modules and explicit tools, but a large brain dispatcher | Useful modularity pattern for future refactoring; substring routing is not a substitute for action validation |
| News | NewsPlugin fetches Google News RSS with a timeout | Website search/navigation, not a dedicated RSS reader | A genuine useful integration candidate, requiring network-data handling and tests before adoption |
| Weather/email/home | Fixed weather string, fictional inbox entries, in-memory simulated device state | No connected email, smart-home or phone integration | Neither supplies those real integrations in the reviewed paths |
| Reminders | In-memory text entries; no timed delivery scheduler in CalendarPlugin | No scheduled reminder integration | Do not present either as working notifications |
| Testing | No test suite or CI workflow present in reviewed tree | Acceptance, regression tests and cross-platform CI | Ultron has stronger visible automated verification; test count alone does not prove live reliability |

## Source anchors

All links below pin the reviewed revision:

- [Active dashboard](https://github.com/harsh-raj00/my-jarvis/blob/7386427d8e6096607fa66ca4c71677e3afd0c2b7/frontend/src/components/Dashboard/JarvisDashboard.jsx)
- [LLM service](https://github.com/harsh-raj00/my-jarvis/blob/7386427d8e6096607fa66ca4c71677e3afd0c2b7/backend/src/services/llm_service.py)
- [Plugin manager](https://github.com/harsh-raj00/my-jarvis/blob/7386427d8e6096607fa66ca4c71677e3afd0c2b7/backend/src/services/plugin_manager.py)
- [Calendar](https://github.com/harsh-raj00/my-jarvis/blob/7386427d8e6096607fa66ca4c71677e3afd0c2b7/backend/src/plugins/calendar_plugin.py)
- [System](https://github.com/harsh-raj00/my-jarvis/blob/7386427d8e6096607fa66ca4c71677e3afd0c2b7/backend/src/plugins/system_plugin.py)
- [News](https://github.com/harsh-raj00/my-jarvis/blob/7386427d8e6096607fa66ca4c71677e3afd0c2b7/backend/src/plugins/news_plugin.py)
- [Weather](https://github.com/harsh-raj00/my-jarvis/blob/7386427d8e6096607fa66ca4c71677e3afd0c2b7/backend/src/plugins/weather_plugin.py)
- [Email](https://github.com/harsh-raj00/my-jarvis/blob/7386427d8e6096607fa66ca4c71677e3afd0c2b7/backend/src/plugins/email_plugin.py)
- [Simulated home](https://github.com/harsh-raj00/my-jarvis/blob/7386427d8e6096607fa66ca4c71677e3afd0c2b7/backend/src/plugins/smart_home_plugin.py)
- [License](https://github.com/harsh-raj00/my-jarvis/blob/7386427d8e6096607fa66ca4c71677e3afd0c2b7/LICENSE): MIT, copyright 2026 Harsh Raj. Reuse of covered code must retain its notice and permission text.

## Adopted in Ultron

The ideas of local informational handlers and discoverable capabilities inspired
an independent implementation in `ultron_control/local_facts.py`. No source,
assets, branding or dependencies were copied from my-jarvis. Ultron's existing
ownership/license terms are unchanged.

- “What time is it?” and “What is today's date?” read the computer's local clock,
  include the UTC offset and bypass model inference. They do not retrieve calendar appointments.
- “How much disk space is free?” reads the volume containing the user's home
  folder, reports GiB, and explicitly does not claim to inspect every drive.
  Permission/OS errors return unavailable, not invented measurements.
- “What can you do?” describes implemented capabilities and identifies email,
  phone, smart-home and scheduled-reminder integrations as unconnected.
- These routes match whole informational requests. They do not silently consume
  a mixed command such as “what time is it and open Calculator.” Such requests
  remain with the existing planner and validation.

## Worth doing later

1. A lightweight dashboard with command transcript, actual outcomes, connection
   status and stop-speaking control, connected to Ultron's existing event bus.
2. A reviewed capability registry to reduce the brain dispatcher's size while
   preserving preflight, request grounding and truthful execution results.
3. A bounded RSS news reader that labels publication times, preserves source
   links and treats feed content as untrusted data rather than instructions.

None of these larger features is claimed implemented by this change. There is no
reason to replace Ultron's working core or adopt paid APIs to obtain these benefits.
