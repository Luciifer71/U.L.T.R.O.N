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
