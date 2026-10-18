# Read-only Google updates (Windows, optional)

After one-time consent, the brain starts a background sync on startup and polls
approximately every five minutes, with capped backoff on failure. Existing wake-word
sessions accept `check my emails`, `email updates`, `check my calendar`, and
`give me my updates`. Clap detection is not implemented. Ultron must be running;
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
