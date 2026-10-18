"""Optional read-only Google updates. Remote text never enters the action planner."""
from __future__ import annotations
import asyncio
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import time

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly',
          'https://www.googleapis.com/auth/calendar.events.readonly']
SERVICE = 'Ultron.Google.ReadOnly'


def private_dir():
    root = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local/share')) / 'Ultron' / 'google'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def vault():
    # No silent plaintext fallback; this integration targets Windows.
    from keyring.backends.Windows import WinVaultKeyring
    return WinVaultKeyring()


def credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    saved = vault().get_password(SERVICE, 'credentials')
    if not saved:
        raise RuntimeError('Google is not connected')
    creds = Credentials.from_authorized_user_info(json.loads(saved), SCOPES)
    if not creds.valid:
        creds.refresh(Request())
        vault().set_password(SERVICE, 'credentials', creds.to_json())
    return creds


def connect(client_file):
    from google_auth_oauthlib.flow import InstalledAppFlow
    config = json.loads(Path(client_file).read_text(encoding='utf-8'))
    installed = config.get('installed', {})
    if (installed.get('auth_uri') != 'https://accounts.google.com/o/oauth2/auth'
            or installed.get('token_uri') != 'https://oauth2.googleapis.com/token'):
        raise ValueError('Use an original Google Desktop OAuth client JSON.')
    flow = InstalledAppFlow.from_client_config(config, SCOPES, autogenerate_code_verifier=True)
    creds = flow.run_local_server(host='127.0.0.1', port=0, timeout_seconds=300,
                                  access_type='offline', prompt='consent')
    if not creds.has_scopes(SCOPES):
        raise ValueError('Both read-only permissions are required.')
    # Reset old account cache before storing a new account's credentials.
    db = private_dir() / 'updates.sqlite3'
    db.unlink(missing_ok=True)
    vault().set_password(SERVICE, 'credentials', creds.to_json())
    (private_dir() / 'enabled').touch(mode=0o600)


def disconnect():
    (private_dir() / 'enabled').unlink(missing_ok=True)
    try:
        vault().delete_password(SERVICE, 'credentials')
    except Exception:
        raise RuntimeError('Could not remove the Windows credential; check Credential Manager.') from None
    (private_dir() / 'updates.sqlite3').unlink(missing_ok=True)


def request_kind(prompt):
    text = re.sub(r'[^a-z0-9 ]', '', prompt.lower()).strip()
    text = re.sub(r'^(?:(?:hey ultron|okay|please|can you|could you) )+', '', text)
    if text in {'whats on my calendar', 'what is on my calendar', 'whats on my calendar today', 'what is on my calendar today'}:
        return 'calendar'
    if re.fullmatch(r'(?:check|read|show|give me|what are|any)(?: my| me)? (?:email|emails|mail|gmail)(?: updates)?', text):
        return 'mail'
    if re.fullmatch(r'(?:check|read|show|give me|what are|any)(?: my| me)? (?:calendar|calendar updates|events|appointments)(?: today)?', text):
        return 'calendar'
    if text in {'email update', 'email updates', 'my email updates'}:
        return 'mail'
    if text in {'my updates', 'give me my updates', 'calendar update', 'calendar updates'}:
        return 'calendar' if text.startswith('calendar') else 'all'
    return None


def clean(value, limit=160):
    return re.sub(r'\s+', ' ', ''.join(c for c in str(value) if c.isprintable())).strip()[:limit]


def body_text(payload):
    # Bounded inline plain text only; no attachments, links or HTML execution.
    result = []
    stack = [payload]
    while stack and len(result) < 100:
        part = stack.pop()
        stack.extend(part.get('parts', [])[:100])
        if part.get('mimeType') == 'text/plain':
            data = part.get('body', {}).get('data', '')[:350000]
            try:
                result.append(base64.urlsafe_b64decode(data + '=' * (-len(data) % 4)).decode('utf-8', 'replace'))
            except (ValueError, TypeError):
                pass
    return '\n'.join(result)[:250000]


def classify(message):
    labels = message.get('labelIds', [])
    headers = {h['name'].lower(): h.get('value', '') for h in message.get('payload', {}).get('headers', [])}
    text = (headers.get('subject', '') + ' ' + message.get('snippet', '') + ' ' + body_text(message.get('payload', {}))).lower()
    reasons = []
    if 'IMPORTANT' in labels:
        reasons.append('Gmail marked important')
    if re.search(r'\b(deadline|action required|security alert|payment due|interview|appointment|urgent)\b', text):
        reasons.append('priority keywords; review needed')
    if 'SPAM' in labels or 'TRASH' in labels:
        reasons = []
    return clean(headers.get('subject', '(no subject)')), '; '.join(reasons)


class GoogleUpdates:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else private_dir()
        self.status = 'Not connected. Run google_connect.py connect once on this Windows computer.'
        self.checked = 0.0
        self.stopping = False
        self.scanned = 0
        self.important = 0
        self.calendar_count = 0
        self.complete = False
        self.calendar_complete = False
        self.events = []
        self.mail_ok = False
        self.calendar_ok = False
        self.enabled = (self.root / 'enabled').exists()

    def reply(self, kind='all'):
        if not self.enabled:
            return self.status
        if not self.checked:
            return 'Google updates are waiting for the first successful sync. ' + self.status
        age = int(max(0, time.time() - self.checked))
        mail = (f'Mail cache: {self.scanned} messages reviewed; {self.important} potentially important (cached, may include deleted mail). '
                f'Archive pass {"complete" if self.complete else "in progress"}. ')
        calendar = f'Primary calendar: {self.calendar_count} events in the next 24 hours' + ('. ' if self.calendar_complete else ' (partial list). ')
        # Subjects and event titles stay out of voice logs/support bundles.
        return (f'Google snapshot {age} seconds old. ' + self.status + ' ' +
                (mail if kind != 'calendar' and self.mail_ok else '') +
                (calendar if kind != 'mail' and self.calendar_ok else '') +
                'Use google_connect.py review for private titles and priority reasons. Importance is a heuristic, not a guarantee.')

    def sync(self, gmail=None, calendar=None):
        if gmail is None:
            from googleapiclient.discovery import build
            import google_auth_httplib2
            import httplib2
            creds = credentials()
            def client(api, version):
                http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=15))
                return build(api, version, http=http, cache_discovery=False)
            gmail, calendar = client('gmail', 'v1'), client('calendar', 'v3')
        self.root.mkdir(parents=True, exist_ok=True)
        errors = []
        with sqlite3.connect(self.root / 'updates.sqlite3') as db:
            db.execute('CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, subject TEXT, reason TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT)')
            def state(key, default=''):
                row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
                return row[0] if row else default
            def put(key, value):
                db.execute('INSERT OR REPLACE INTO state VALUES (?, ?)', (key, str(value)))
            try:
                messages = gmail.users().messages()
                # Refresh newest page each cycle while progressing a durable full archive pass.
                pages = [messages.list(userId='me', maxResults=25, includeSpamTrash=True).execute(num_retries=0)]
                token = state('page')
                if token:
                    pages.append(messages.list(userId='me', maxResults=25, includeSpamTrash=True, pageToken=token).execute(num_retries=0))
                for page in pages:
                    for item in page.get('messages', []):
                        if self.stopping:
                            return
                        message = messages.get(userId='me', id=item['id'], format='full').execute(num_retries=0)
                        subject, reason = classify(message)
                        db.execute('INSERT OR REPLACE INTO messages VALUES (?, ?, ?)', (item['id'], subject, reason))
                # Advance only after entire batch succeeds. Periodically restart to refresh old labels.
                put('page', pages[-1].get('nextPageToken', ''))
                self.complete = not pages[-1].get('nextPageToken')
                self.scanned = db.execute('SELECT COUNT(*) FROM messages').fetchone()[0]
                self.important = db.execute("SELECT COUNT(*) FROM messages WHERE reason != ''").fetchone()[0]
                self.mail_ok = True
            except Exception:
                errors.append('Mail sync unavailable; authorization, network or quota may need attention.')
                self.mail_ok = False
            try:
                now = datetime.now(timezone.utc)
                response = calendar.events().list(calendarId='primary', timeMin=now.isoformat(),
                    timeMax=(now + timedelta(hours=24)).isoformat(), singleEvents=True,
                    orderBy='startTime', maxResults=100).execute(num_retries=0)
                self.events = [{'title': clean(e.get('summary', '(untitled)')),
                                'start': e.get('start', {})} for e in response.get('items', [])]
                self.calendar_count = len(self.events)
                self.calendar_complete = not response.get('nextPageToken')
                put('calendar', json.dumps(self.events))
                self.calendar_ok = True
            except Exception:
                errors.append('Calendar sync unavailable; authorization, network or quota may need attention.')
                self.calendar_ok = False
            if self.mail_ok or self.calendar_ok:
                self.checked = time.time()
                put('checked', self.checked)
        self.status = ' '.join(errors) or 'Read-only sync available.'

    async def run(self, notify):
        if not self.enabled:
            return
        previous = None
        failures = 0
        while True:
            try:
                await asyncio.to_thread(self.sync)
                failures = 0 if self.mail_ok and self.calendar_ok else failures + 1
                count = self.important
                if self.mail_ok and (previous is None or count > previous):
                    await notify(f'Google update: {count} potentially important messages in the scanned archive. Ask for email or calendar updates.')
                if self.mail_ok:
                    previous = count
            except asyncio.CancelledError:
                self.stopping = True
                raise
            except Exception:
                self.status = 'Google sync unavailable. Reconnect if access was revoked or expired.'
                failures += 1
            await asyncio.sleep(min(1800, 300 * 2 ** min(failures, 3)))
