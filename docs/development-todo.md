# Development priorities

Existing licensing and ownership terms remain unchanged. These ideas are independently
implemented or planned; no God's Eye View source or datasets have been copied.

## Current increment
- [x] Optional read-only Google OAuth, Windows token storage, background polling.
- [x] Resumable bounded mailbox scan, local priority reasons, primary-calendar snapshot.
- [x] Voice status from cached evidence; private titles excluded from voice logs.
- [ ] Owner's Google consent and live Windows account verification (cannot automate consent).
- [ ] Gmail history sync, deleted-message reconciliation, per-message durable alert delivery.
- [ ] User-adjustable importance rules and secondary calendars.

## Adapt useful God's Eye View architecture
- [ ] Shared workspace context: selected file, active window, observed-at timestamp.
- [ ] Evidence envelopes across tools: source, freshness, partial/degraded state.
- [ ] Durable task checkpoints, bounded retries and cancellation; do not repeat side effects.
- [ ] Operational dashboard for current task, pending plan, health and stop controls.
- [ ] Generation-scoped referents so late/cancelled results cannot restore old context.
- [ ] Paired, revocable device authentication before future iPhone integration.
- [ ] Provider recovery based on valid fresh data, not merely an open connection.

Source of design inspiration: bilawalsidhu/gods-eye-view at
1df2a272cf7cfbb2f1a4c637c897e90719b0af95. Retain Ultron's local-first budget and
verified-action contracts. “Always available” means bounded recovery and user control,
not endless inference, unlimited retries or an assistant that cannot be stopped.

## Visual entity and presence
- [x] Phase A: body language (springs, shockwaves, idle thoughts, awakening).
- [x] Phase B: live data (task steps as rings, voice, words, model activity, system load).
- [x] Phase C: cinematic lens pass, glitches, hologram scan, lightning.
- [x] Phase D: optional camera presence (the entity notices the user arrive; off by default).

## Hand gestures (see `gestures.md` for the mapping table)
- [x] G1: vision service (sole camera owner), hand tracking and pose recognition,
      gesture mode on by double clap / voice / Ops button, off by both palms / voice /
      button / 3 min idle; holographic hands and GESTURE MODE heading in the UI.
- [x] G2: air mouse: pointer, click, double-click, drag, scroll (action daemon, gesture mode only, audited).
- [ ] G3: windows: grab and move, throw to the monitor in any direction (real monitor
      layout), two-hand resize.
- [ ] G4: clipboard grab/release, swipes, twist volume, palm pause, frame screenshot,
      fist lock (always confirmed), both-palms push to stop.
- [ ] G5: holographic workspace (panels you can grab in the UI).
- [ ] G6: custom gestures and per-user calibration; later a hologram output mode.

## Adopt OpenJarvis ideas (see `openjarvis-review.md`; independent implementations)
- [ ] Phase E: automatic long-term memory; scheduler and reminders.
- [ ] Phase F: spoken morning briefing; proactive agent with approval tiers;
      prompt-injection scanning, taint tracking and loop guard.
- [ ] Phase G: Telegram phone channel (paired, allow-listed).
- [ ] Phase H: optional local Kokoro voice.
- [ ] Phase I: allow-listed MCP tool plugins through the capability broker.
