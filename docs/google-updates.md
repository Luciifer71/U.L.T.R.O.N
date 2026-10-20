# Read-only Google updates (Windows, optional)

After one-time consent, the brain starts a background sync on startup and polls
approximately every five minutes, with capped backoff on failure. Existing wake-word
sessions accept `check my emails`, `email updates`, `check my calendar`, and
`give me my updates`, `what are my latest email updates?`, and `do I have any new emails?`. Clap detection is not implemented. Ultron must be running;
this is not a cloud service or an iPhone notification service.

## One-time account connection

Google requires the account owner to consent. A ChatGPT Gmail connection does not
transfer credentials to this independent application. No account is connected by
installing this code.

1. In your own Google Cloud project, enable Gmail API and Google Calendar API.
   Configure the OAuth consent screen, add yourself as a test user if in testing,
   and create a **Desktop app** OAuth client. Download its JSON outside this repository.
2. Stop Ultron. Run in PowerShell:
   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements-google.txt
   .\.venv\Scripts\python.exe .\google_connect.py connect --client "C:\path\client_secret.json"
   ```
3. Sign in to the intended account and grant both read-only scopes in Google's
   browser consent screen. Restart the normal launcher or `start-qwen3-trial.cmd`.

Tokens are held by Windows Credential Manager, with no plaintext fallback. Local
cache lives under `%LOCALAPPDATA%\Ultron\google`, outside the repository and support
bundle allowlist. It contains message IDs, subjects, priority reasons and upcoming
event titles/times in plaintext under your Windows user profile. Protect that account.
Bodies are processed in memory, not stored. Private titles are not spoken or sent
to Ollama. Review them locally with:

```powershell
.\.venv\Scripts\python.exe .\google_connect.py review
```

Stop Ultron before connecting another account or disconnecting:
```powershell
.\.venv\Scripts\python.exe .\google_connect.py disconnect
```
Also revoke access in your Google account's third-party connections. Disconnect
removes local credentials/cache, not the Google-side grant. In OAuth testing mode,
Google can expire refresh tokens after seven days; reconnect when necessary.

## Coverage and honest limits

- Read-only Gmail and primary Calendar, no send/delete/mark-read/change-label tools.
  “Flagging” means local priority reasons and count announcements, not Gmail labels.
- Every sync refreshes the newest 25 messages plus the next 25-message archive page,
  including spam/trash. Checkpoints advance only after a successful page batch.
  Large mailboxes need many cycles. Completed passes restart to refresh older data.
- Full Gmail message payloads are fetched. Classification uses Gmail's IMPORTANT
  label, subject, snippet and bounded inline plain text. Attachments and HTML-only
  bodies are not fully analyzed. Spam/trash do not generate priority flags.
- Importance is a simple English keyword/label heuristic, not a guarantee. Counts
  are cached review records, can include deleted messages, and are not live inbox
  counts. No claim that every email has been reviewed until an archive pass finishes.
- The next 24 hours of the primary calendar are read, with a 100-event cap and an
  explicit partial indicator. Shared/secondary calendars are not included.
- Startup announces scanned priority counts; later announcements occur when that
  count rises. This can announce old archive discoveries and can miss a new priority
  message if another loses its flag. It is not a reliable urgent-alert service yet.
- Requests have network timeouts; partial failures remain visible. Cancelling stops
  the next work item; an in-flight request may finish before shutdown completes.
- No message content can execute commands or modify tools. The integration never
  sends remote text to the action planner and never opens email links.
- No paid model API is used. Google quota, OAuth verification and provider policies
  still apply. Automated tests use fake services; live account access requires consent.

References: [Google Desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app),
[Gmail quickstart](https://developers.google.com/workspace/gmail/api/quickstart/python),
[Calendar events](https://developers.google.com/workspace/calendar/api/v3/reference/events/list).

## Responsive replies and speech controls

Google status requests bypass the model/action queue once the brain is online.
Voice responses give short counts and scan/availability limitations; the private
review command retains detailed titles. These are cached counts across reviewed
mail, not a filtered count of unread messages or a summary of every message.
Repeated status replies are combined while pending, suppressed during matching
speech and for ten seconds afterwards, and expire after twenty seconds in the
speech queue. Each typed request still receives its own correlated text response.

Run `stop-ultron-speech.cmd` (or `send_intent.py "stop speaking"`) to stop current
queued voice playback and clear pending speech. It does not cancel physical actions
or disable future background notifications. Spoken interruption during playback is
not supported: the microphone is intentionally muted while Ultron speaks.

The listener starts muted, requests the current speaker state and periodically
refreshes it. It rejects older idle snapshots after newer speaking events. If the
voice daemon is unreachable, capture stays muted; start/restart the action daemon.
Restart all three components together after updating this protocol.

### Live regression checklist

1. Stop components, pull main, run `verify_ultron.py`, then launch the trial.
2. Stay silent during startup. The listener must not dispatch Ultron's own Google
   announcement as a user command. Wait for STANDBY after calibration.
3. Ask "What are my latest email updates?" and "Check my calendar." Expect short
   cached status, no Ollama planning call for these requests, and no false claim
   that connected mail is inaccessible. Allow speech generation/network latency.
4. Ask an ordinary model question, then use a separate terminal to send
   `send_intent.py "check my emails" --timeout 5`. Expect a correlated text reply
   within five seconds even if model inference is busy. Speech may wait its turn.
5. Send the same email-status request three times quickly. Text responses should
   arrive for each request, but speech should not read three matching status
   paragraphs. Different email/calendar requests may each have one short reply.
6. During speech run `stop-ultron-speech.cmd`. Expect playback to stop and queued
   speech to clear. Then ask a new question to verify speech still works.
7. Leave Ultron running for another sync interval. Counts can increase as archive
   scanning progresses. This does not necessarily mean newly arrived mail.
8. Run `collect-ultron-report.cmd --model qwen3:8b --tests` and share the ZIP with
   your observations. The bundle excludes Google credentials/cache and cannot
   independently prove what you heard or which Google account you selected.

Automated tests simulate slow inference, queue expiry/coalescing, cancellation,
actual daemon playback cleanup, state snapshots, and stale speaking-state updates.
Live microphone echo suppression and perceived latency still require this laptop check.

### Request routing and verification

Personal email/calendar requests use a bounded, deterministic router shared by
both the immediate reply lane and the brain. Requests such as “Can you brief me
about my latest email updates?” and “Is there any later latest calendar updates?”
return the cached integration status without waiting for the model. Unknown
qualifiers, requested senders/date ranges and mixed desktop actions produce a
clarification rather than a fabricated account-access answer. Google mutations
receive an explicit read-only limitation. Negated, quoted and hypothetical text
is not treated as consent to read account data. Routing input is capped at 4096
characters; larger inputs remain outside this shortcut.

These replies are still **counts**, not message summaries: email importance is
heuristic over the scanned archive, and calendar coverage is the primary calendar
for the next 24 hours. “Latest” does not turn archive counts into new/unread counts.
Disconnected, first-sync, unavailable, partial and stale snapshots are reported
separately. A background authorization/client failure invalidates previous success
flags instead of presenting a failed connection as a healthy cached sync.

After updating and restarting, run `verify_ultron.py`, then use `send_intent.py`
with each quoted request above and `--timeout 5`. Also try “Check my calendar next
week” (clarification) and “Delete my emails” (read-only limitation, no deletion).
Finally say “Open calculator” to check the existing action path. Collect one
support ZIP using `collect-ultron-report.cmd --model qwen3:8b --tests` if needed.

Automated tests cover routing boundaries, sync states, failure recovery flags and
200 correlated requests without filling the model queue. This is regression
evidence, not a production load benchmark or proof of live OAuth/audio health.
