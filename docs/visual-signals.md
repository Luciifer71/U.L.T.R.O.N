# Live signals for the visual entity

The visual entity (`ultron-ui`) reacts to what ULTRON is really doing. Components
publish small, content-free display hints on NATS under `ultron.signal.<kind>`
(`src/ultron/control/signals.py`). The UI turns them into motion
(`ultron-ui/src/entity/liveSignals.ts`).

| Subject | Sent by | Payload | Shown as |
| --- | --- | --- | --- |
| `ultron.signal.step` | brain, for every task step | `taskId`, `index`, `total`, `kind` (action type only), `state` | each step lights its own ring: racing pulse while running, white-gold flash when done, red strobe and broken segments when failed, dim when skipped |
| `ultron.signal.voice` | listener, while you speak (max 15/s, then a final 0) | `level` 0..1 | ripples through the core |
| `ultron.signal.model` | brain, around each model request | `phase` start/end, `seconds` | rapid neural cascades that build up while the model thinks |
| `ultron.signal.vitals` | brain, every 2 s | `cpu`, `memory` 0..1 | core pressure: hotter core and shivering rings, only under real strain |

The UI also reads existing subjects: `ultron.status.speaking` (the core swells in a
speech rhythm while ULTRON talks), `ultron.intent` (each word of a request streams
into the core) and `ultron.voice` (each word of a reply streams out).

## Guarantees

- **Content-free:** signals never carry prompts, transcripts, audio, file paths or
  app names. A step reports `open_resource`, never the file or app it opened.
- **Display only:** publishing is fire-and-forget and can never fail or delay a task.
  The action daemon does not subscribe to `ultron.signal.*`, and the UI never acts on
  them.
- **Safe without a backend:** with no signals every live value rests at zero and the
  entity shows its normal state behaviour. A lost "end" or final voice level times
  out (model after 2 minutes, voice after 1.5 s).
