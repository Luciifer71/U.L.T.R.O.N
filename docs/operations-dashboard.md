# Operations dashboard

A side panel in the visual UI (`ultron-ui`) that shows what Ultron is doing and
lets you stop it. Press the backtick key (`` ` ``) or use the **Ops** button to show
or hide it; the choice is remembered in the browser.

Start Ultron as usual (`.\start-ultron.cmd`), then the UI:

```powershell
npm ci --prefix .\ultron-ui
npm run dev --prefix .\ultron-ui
```

## What it shows

| Section | Source |
| --- | --- |
| **Now** | The task the brain is working on, its stage (planning, executing, stopping) and each step's state. |
| **Transcript** | Requests (spoken or typed) and Ultron's replies seen on the bus while the panel is open. |
| **Command box** | Sends a typed request exactly like a spoken one. Replies are still spoken aloud. |
| **Health** | Brain (answers status requests), listener and action daemon (heartbeat every 5 s, offline after ~16 s), Ollama, Spotify and Google. |
| **Recent tasks** | The last 20 tasks from the task database with their recorded outcome. |

## Stop

**Stop** does three things:

1. Stops current speech and clears queued speech.
2. Drops requests that are queued but not started.
3. Stops the current task **before its next step**.

A step that is already running (for example an app that is opening) is allowed to
finish. Nothing is undone. The task is recorded as `cancelled`, and the reply says
how many steps had already run. That reply is shown on the panel, not spoken.

## How it works

The panel talks to the brain over the existing local NATS WebSocket
(`ws://127.0.0.1:9222`):

| Subject | Direction | Purpose |
| --- | --- | --- |
| `ultron.ops.status` | request/reply | Snapshot: current task, queue size, components, services, recent tasks. Polled every 2 s. |
| `ultron.ops.stop` | request/reply | Stop as described above. |
| `ultron.ops.heartbeat` | publish | Liveness from the listener and action daemon. |
| `ultron.intent`, `ultron.voice` | subscribe / publish | Transcript and typed commands. |

The action daemon ignores every `ultron.ops.*` message, so dashboard traffic is
never spoken or executed. The NATS WebSocket has no authentication: keep it bound
to `127.0.0.1` (as in `docker-compose.yml`) and do not expose it on a network.

If the 3D entity fails to start (no WebGPU), the page shows a short notice and the
panel keeps working.
