"""Optional read-only Google updates. Remote text never enters the action planner."""
from __future__ import annotations
import asyncio
from contextlib import ExitStack, closing
import base64
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import time

from ultron.control.google_routing import request_kind, route_request

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly',
          'https://www.googleapis.com/auth/calendar.events.readonly']
SERVICE = 'Ultron.Google.ReadOnly'



class GoogleNotConnectedError(RuntimeError):
    pass


class GoogleStageError(RuntimeError):
    def __init__(self, stage, cause):
        self.stage, self.cause = stage, cause
        super().__init__('Google connection stage failed')


def failure_details(error):
    """Return allowlisted facts only; never serialize exception messages/bodies."""
    stage = error.stage if isinstance(error, GoogleStageError) else 'api'
    error = error.cause if isinstance(error, GoogleStageError) else error
    classes = {(c.__module__, c.__name__) for c in type(error).__mro__}
    status = getattr(getattr(error, 'resp', None), 'status', None)
    oauth = next((arg.get('error') for arg in error.args
                  if isinstance(arg, dict) and arg.get('error') in
                  {'invalid_grant', 'invalid_client', 'unauthorized_client', 'temporarily_unavailable'}), None)
    if isinstance(error, GoogleNotConnectedError):
        code, advice = 'not_connected', 'No saved Google credentials were found.'
    elif isinstance(error, ImportError):
        code, advice = 'dependency', 'Install requirements/google.txt with the Ultron Python interpreter.'
    elif ('google.auth.exceptions', 'RefreshError') in classes:
        if oauth == 'invalid_grant':
            code, advice = 'reauthorization_required', 'Google rejected the saved authorization. Reconnect this account. Expiry or revocation are possible; the exact reason is not established.'
        elif oauth in {'invalid_client', 'unauthorized_client'}:
            code, advice = 'oauth_client', 'Google rejected the OAuth client. Check the Desktop client configuration.'
        elif getattr(error, 'retryable', False) or oauth == 'temporarily_unavailable':
            code, advice = 'service', 'Google token service is temporarily unavailable; sync will retry.'
        else:
            code, advice = 'token_refresh', 'Google token refresh failed. Run run_ultron.py google doctor for connection status.'
    elif isinstance(error, (TimeoutError, ConnectionError)) or any(
            module in {'google.auth.exceptions', 'requests.exceptions', 'httplib2', 'socket'}
            and name in {'TransportError', 'ConnectionError', 'Timeout', 'HttpLib2Error', 'gaierror'}
            for module, name in classes):
        code, advice = 'network', 'A network connection or timeout interrupted sync; it will retry.'
    elif status == 401:
        code, advice = 'authentication', 'Google rejected authentication; reconnect may be required.'
    elif status == 403:
        code, advice = 'forbidden', 'Google denied access; check API enablement, permissions and quota.'
    elif status == 429:
        code, advice = 'quota', 'Google rate limit reached; sync will retry.'
    elif isinstance(status, int) and 500 <= status <= 599:
        code, advice = 'service', 'Google service is temporarily unavailable.'
    elif stage in {'credential_read', 'credential_save'}:
        code, advice = 'credential_store', 'Windows Credential Manager could not read or save Google access.'
    elif stage == 'credential_decode':
        code, advice = 'credential_format', 'Saved Google credentials could not be loaded. Reconnect this account.'
    elif isinstance(error, sqlite3.Error):
        code, advice = 'cache', 'The local Google cache is unavailable; check disk access and competing Ultron instances.'
    else:
        code, advice = 'unknown', 'The cause is not established; inspect connection setup and diagnostics.'
    return {'stage': stage, 'code': code, 'advice': advice}


def sync_failure(service, error):
    details = failure_details(error)
    logging.getLogger(__name__).warning('[GOOGLE SYNC ERROR]: service=%s stage=%s code=%s',
                                      service, details['stage'], details['code'])
    return f"{service} sync unavailable. {details['advice']}"


def connection_stage(stage, operation):
    try:
        return operation()
    except Exception as error:
        raise GoogleStageError(stage, error) from None


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
    saved = connection_stage('credential_read', lambda: vault().get_password(SERVICE, 'credentials'))
    if not saved:
        raise GoogleNotConnectedError('Google is not connected')
    creds = connection_stage('credential_decode',
                            lambda: Credentials.from_authorized_user_info(json.loads(saved), SCOPES))
    if not creds.valid:
        request = Request()
        def bounded_request(*args, **kwargs):
            kwargs.setdefault('timeout', 15)
            return request(*args, **kwargs)
        try:
            connection_stage('token_refresh', lambda: creds.refresh(bounded_request))
        finally:
            session = getattr(request, 'session', None)
            if session is not None:
                session.close()
        connection_stage('credential_save', lambda: vault().set_password(SERVICE, 'credentials', creds.to_json()))
    return creds



def google_clients():
    from googleapiclient.discovery import build
    import google_auth_httplib2
    import httplib2
    creds = credentials()
    def client(api, version):
        http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=15))
        try:
            return connection_stage('client_build',
                                    lambda: build(api, version, http=http, cache_discovery=False))
        except BaseException:
            http.close()
            raise
    gmail = client('gmail', 'v1')
    try:
        return gmail, client('calendar', 'v3')
    except BaseException:
        gmail.close()
        raise


def connection_diagnostics():
    """Live bounded read checks, without downloading message bodies or changing cache."""
    report = {'scope': 'Live read-only Google connection checks; no email contents or tokens included.'}
    try:
        gmail, calendar = google_clients()
    except Exception as error:
        report['connection'] = {'status': 'failed', **failure_details(error)}
        return report
    report['connection'] = {'status': 'ok'}
    now = datetime.now(timezone.utc)
    checks = {
        'gmail': lambda: gmail.users().messages().list(userId='me', maxResults=1).execute(num_retries=0),
        'calendar': lambda: calendar.events().list(calendarId='primary', timeMin=now.isoformat(),
            timeMax=(now + timedelta(hours=24)).isoformat(), singleEvents=True,
            maxResults=1).execute(num_retries=0),
    }
    try:
        for name, check in checks.items():
            try:
                check()
                report[name] = {'status': 'ok'}
            except Exception as error:
                report[name] = {'status': 'failed', **failure_details(error)}
    finally:
        for service in (gmail, calendar):
            close = getattr(service, 'close', None)
            if close:
                close()
    return report


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
        self.status = 'Not connected. Run run_ultron.py google connect once on this Windows computer.'
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
        if self.enabled:
            self.status = 'Waiting for the first successful sync.'

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
                'Use run_ultron.py google review for private titles and priority reasons. Importance is a heuristic, not a guarantee.')

    def spoken_reply(self, kind='all'):
        if kind == 'connection':
            return ('I support read-only Gmail and Google Calendar updates. ' +
                    (self.status if self.enabled else 'Google is not connected on this computer.'))
        if kind == 'unsupported':
            return 'Google access is read-only. I cannot send, delete or change email or calendar events.'
        if kind == 'clarify':
            return 'I can report cached email importance counts and primary-calendar events for the next 24 hours. Please ask for email updates, calendar updates, or both; other actions need a separate request.'
        if not self.enabled:
            return 'Not connected to Google on this computer.'
        if not self.checked:
            return 'Google updates are not ready yet. ' + (self.status if 'unavailable' in self.status else 'Waiting for the first successful sync.')
        parts = []
        if kind != 'calendar':
            if self.mail_ok:
                parts.append(f'{self.important} potentially important emails among {self.scanned} reviewed.'
                             + (' The archive scan is still in progress.' if not self.complete else ''))
            else:
                parts.append('Email sync is unavailable. Check the connection diagnostics.')
        if kind != 'mail':
            if self.calendar_ok:
                parts.append(f'{self.calendar_count} events on your primary calendar in the next 24 hours.'
                             + (' This list is partial.' if not self.calendar_complete else ''))
            else:
                parts.append('Calendar sync is unavailable. Check the connection diagnostics.')
        age = max(0, int(time.time() - self.checked))
        if age > 600:
            parts.append(f'This snapshot is {age // 60} minutes old.')
        return ' '.join(parts)

    def sync(self, gmail=None, calendar=None):
        with ExitStack() as owned:
            if gmail is None:
                gmail, calendar = google_clients()
                for service in (gmail, calendar):
                    owned.callback(service.close)
            return self._sync(gmail, calendar)

    def _sync(self, gmail, calendar):
        self.root.mkdir(parents=True, exist_ok=True)
        errors = []
        with closing(sqlite3.connect(self.root / 'updates.sqlite3')) as db, db:
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
            except Exception as error:
                errors.append(sync_failure('Mail', error))
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
            except Exception as error:
                errors.append(sync_failure('Calendar', error))
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
            except Exception as error:
                self.mail_ok = self.calendar_ok = False
                self.status = sync_failure('Google', error)
                failures += 1
            await asyncio.sleep(min(1800, 300 * 2 ** min(failures, 3)))
