# iPhone companion milestone

Status: planned, not implemented or validated. Requested for the user's iPhone 14.

## Desired behavior

- Send progress, completion and failure updates for tasks the user assigns to Ultron.
- Surface important events and email alerts according to user-defined priorities.
- Allow follow-up instructions and explicit acknowledgements from the phone.
- Eventually provide call-based updates for user-selected urgent events.

## Constraints and acceptance criteria

- Current API budget is zero. Evaluate free approaches first; do not enable paid services without approval.
- Assess iOS delivery, background operation, connectivity and provider limitations before selecting an implementation. Ordinary telephone calls are a separate feasibility/cost decision, not a promised free feature.
- Email access requires account authorization. Receiving alerts does not authorize sending mail, replying, deleting messages or contacting other people.
- Task updates must use the execution ledger, distinguishing verified completion, dispatch and failure.
- Define quiet hours, urgency rules, notification frequency and an off switch before enabling alerts.
- Authenticate the phone connection and protect credentials; do not expose an unauthenticated desktop-control endpoint.
- Test delivery while the phone is locked, duplicate suppression, reconnection and honest handling of an offline PC.

## Sequence

1. Stabilize local task execution and status reporting.
2. Prototype one-way phone updates for a small set of task events.
3. Add authorized email alerts and optional two-way commands.
4. Evaluate call-based escalation separately.
