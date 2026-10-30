"""Optional Spotify Premium control. Tokens stay in the OS credential vault."""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import urlencode

REDIRECT_URI = 'http://127.0.0.1:8888/callback'
SCOPES = {'user-read-playback-state', 'user-modify-playback-state'}
SERVICE = 'Ultron.Spotify.PKCE'
LOCK = threading.RLock()


class SpotifyError(RuntimeError):
    """Only user-safe, credential-free messages cross the integration boundary."""


def private_dir():
    return Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local/share')) / 'Ultron' / 'spotify'


def configured():
    return (private_dir() / 'enabled').is_file()


def vault():
    if os.name != 'nt':
        raise SpotifyError('Spotify authorization currently supports Windows Credential Manager only.')
    try:
        from keyring.backends.Windows import WinVaultKeyring
        return WinVaultKeyring()
    except ImportError:
        raise SpotifyError('Install requirements/spotify.txt before connecting Spotify.') from None


def pkce_pair():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode().rstrip('=')
    return verifier, challenge


def authorization_url(client_id, state, challenge):
    return 'https://accounts.spotify.com/authorize?' + urlencode(dict(
        client_id=client_id, response_type='code', redirect_uri=REDIRECT_URI,
        code_challenge_method='S256', code_challenge=challenge, state=state,
        scope=' '.join(sorted(SCOPES))))


def safe_text(value, limit=160):
    return re.sub(r'[\x00-\x1f\x7f]', ' ', str(value))[:limit]


def _request(method, url, *, token=None, data=None, body=None):
    import requests
    try:
        with requests.Session() as session:
            with session.request(method, url, headers={'Authorization': 'Bearer ' + token} if token else {},
                                 data=data, json=body, timeout=(5, 10), allow_redirects=False) as response:
                status = response.status_code
                if status == 204:
                    return status, {}
                if status >= 400 or 300 <= status < 400:
                    return status, {}  # Never expose server bodies, tokens or request URLs in errors.
                return status, response.json()
    except (requests.RequestException, ValueError):
        raise SpotifyError('Spotify could not be reached or returned an invalid response. Check the connection.') from None


def token_record(client_id, payload, previous=None):
    previous = previous or {}
    scope = set(payload.get('scope', ' '.join(previous.get('scope', []))).split())
    access = payload.get('access_token')
    refresh = payload.get('refresh_token') or previous.get('refresh_token')
    if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh or not SCOPES <= scope:
        raise SpotifyError('Spotify did not grant the required playback permissions. Reconnect Spotify.')
    try:
        expires = int(payload['expires_in'])
        if not 0 < expires <= 86400:
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise SpotifyError('Spotify returned an invalid token lifetime. Reconnect Spotify.') from None
    return dict(client_id=client_id, access_token=access, refresh_token=refresh,
                scope=sorted(scope), expires_at=time.time() + expires)


def save_record(record):
    try:
        vault().set_password(SERVICE, 'credentials', json.dumps(record))
    except SpotifyError:
        raise
    except Exception:
        raise SpotifyError('Could not save Spotify authorization in Windows Credential Manager.') from None


def disconnect():
    with LOCK:
        store = vault()
        if store.get_password(SERVICE, 'credentials'):
            store.delete_password(SERVICE, 'credentials')
        (private_dir() / 'enabled').unlink(missing_ok=True)
        (private_dir() / 'device.json').unlink(missing_ok=True)


class SpotifyClient:
    def __init__(self, request=None, clock=time.time, sleep=time.sleep):
        self.request = request or _request
        self.clock, self.sleep = clock, sleep

    def _token(self, force=False):
        with LOCK:
            try:
                raw = vault().get_password(SERVICE, 'credentials')
                record = json.loads(raw) if raw else None
                if (not isinstance(record, dict) or not SCOPES <= set(record.get('scope', []))
                        or any(not isinstance(record.get(k), str) or not record[k]
                               for k in ('client_id', 'access_token', 'refresh_token'))):
                    raise ValueError
                if force or float(record['expires_at']) <= self.clock() + 60:
                    status, payload = self.request('POST', 'https://accounts.spotify.com/api/token', data={
                        'grant_type': 'refresh_token', 'refresh_token': record['refresh_token'], 'client_id': record['client_id']})
                    if status != 200:
                        raise SpotifyError('Spotify authorization could not be refreshed. Reconnect Spotify; if rate-limited, try later.')
                    record = token_record(record['client_id'], payload, record)
                    save_record(record)
                return record['access_token']
            except SpotifyError:
                raise
            except Exception:
                raise SpotifyError('Spotify is not connected or its saved authorization is unreadable. Run the Spotify connect command.') from None

    def api(self, method, path, *, body=None):
        if not path.startswith('/') or path.startswith('//'):
            raise SpotifyError('Invalid Spotify API operation.')
        token = self._token()
        status, payload = self.request(method, 'https://api.spotify.com/v1' + path, token=token, body=body)
        if status == 401:
            status, payload = self.request(method, 'https://api.spotify.com/v1' + path,
                                           token=self._token(force=True), body=body)
        if status in {200, 201, 202, 204}:
            return payload
        errors = {
            401: 'Spotify authorization expired or was revoked. Reconnect Spotify.',
            403: 'Spotify denied access. Check Premium, the app user allowlist and playback permissions.',
            404: 'No usable Spotify playback device. Open Spotify and start a track once, then retry.',
            429: 'Spotify is rate-limiting requests. Wait before trying again.',
        }
        raise SpotifyError(errors.get(status, 'Spotify rejected the request. Playback was not confirmed.'))

    def devices(self):
        return [d for d in self.api('GET', '/me/player/devices').get('devices', [])
                if d.get('id') and not d.get('is_restricted')]

    def device(self):
        devices = self.devices()
        try:
            path = private_dir() / 'device.json'
            preferred = json.loads(path.read_text())['id'] if path.exists() else None
        except (ValueError, KeyError, OSError):
            raise SpotifyError('Saved Spotify device preference is unreadable. Select the device again.') from None
        if not devices:
            raise SpotifyError('Spotify reports no available playback devices. Open Spotify on this laptop using the authorized account and start a track once, then repeat the song request.')
        if preferred:
            chosen = [d for d in devices if d['id'] == preferred]
        else:
            chosen = [d for d in devices if d.get('is_active')]
            if not chosen and len(devices) == 1:
                chosen = devices
        if len(chosen) != 1:
            if preferred:
                raise SpotifyError('Your selected Spotify device is offline. Open it, or select an available device with the Spotify device command.')
            raise SpotifyError('Several Spotify devices are available but none is uniquely active. Start playback on the intended device or select it with the Spotify device command.')
        return chosen[0]

    def state(self):
        return self.api('GET', '/me/player')

    def select_device(self, name):
        choices = [d for d in self.devices() if d.get('name', '').casefold() == name.casefold() or d['id'] == name]
        if len(choices) != 1:
            raise SpotifyError('That Spotify device was not uniquely found. Use the devices command and its exact name or ID.')
        root = private_dir(); root.mkdir(parents=True, exist_ok=True)
        (root / 'device.json').write_text(json.dumps({'id': choices[0]['id']}))
        return safe_text(choices[0].get('name', 'device'))

    def find_track(self, query):
        from ultron.control.youtube_playback import clean_music_query, words
        query = clean_music_query(query)
        parts = re.split(r'\s+by\s+', query, maxsplit=1, flags=re.I)
        title, artist = parts[0], parts[1] if len(parts) == 2 else ''
        search = f'track:{title} artist:{artist}' if artist else title
        rows = self.api('GET', '/search?' + urlencode({'q': search, 'type': 'track', 'limit': 10})).get('tracks', {}).get('items', [])
        wanted_title, wanted_artist = words(title), words(artist) - {'the'}
        matches = []
        for row in rows:
            uri = str(row.get('uri', ''))
            names = [a.get('name', '') for a in row.get('artists', [])]
            title_words = words(row.get('name', ''))
            if (not re.fullmatch(r'spotify:track:[A-Za-z0-9]{22}', uri) or row.get('is_playable') is False
                    or not wanted_title <= title_words
                    or not any(wanted_artist <= words(name) for name in names)
                    or (title_words & {'remix', 'live', 'karaoke', 'cover', 'slowed'}) - wanted_title):
                continue
            matches.append((title_words == wanted_title, row))
        if not matches:
            raise SpotifyError('No confident Spotify song match. Please repeat the title and artist.')
        matches.sort(key=lambda item: item[0], reverse=True)
        best = [r for exact, r in matches if exact == matches[0][0]]
        identities = {(r['name'].casefold(), tuple(a.get('name', '').casefold() for a in r.get('artists', []))) for r in best}
        if len(identities) > 1:
            raise SpotifyError('Several Spotify songs match. Please specify the artist and version.')
        row = best[0]
        return row['uri'], safe_text(row['name'] + ' by ' + ', '.join(a['name'] for a in row['artists']))

    def perform(self, action, query=None, volume=None):
        from ultron.control.youtube_playback import PlaybackResult
        def result(text, verified=False):
            return PlaybackResult(True, message=text, data={'state': 'verified' if verified else 'dispatched',
                'verification': {'spotify_state': True} if verified else 'not_observable'})
        try:
            if action == 'status':
                state = self.state(); item = state.get('item') or {}
                if not item:
                    return result('Spotify has no current track.')
                return result(('Playing: ' if state.get('is_playing') else 'Paused: ') + safe_text(item.get('name', 'unknown track')) + '.', True)
            if action not in {'play', 'pause', 'resume', 'next', 'previous', 'queue', 'volume'}:
                raise SpotifyError('Unsupported Spotify command.')
            if action in {'play', 'queue'} and (not isinstance(query, str) or not query.strip() or len(query) > 200):
                raise SpotifyError('Please specify a song title and artist.')
            if action == 'volume' and (type(volume) is not int or not 0 <= volume <= 100):
                raise SpotifyError('Spotify volume must be between 0 and 100.')
            device = self.device()
            params = {'device_id': device['id']}
            uri = None
            if action in {'play', 'queue'}:
                uri, label = self.find_track(query)
                if action == 'queue':
                    self.api('POST', '/me/player/queue?' + urlencode({**params, 'uri': uri}))
                    return result('Spotify accepted the queue request for ' + label + '.')
                self.api('PUT', '/me/player/play?' + urlencode(params), body={'uris': [uri]})
            elif action in {'pause', 'resume'}:
                self.api('PUT', '/me/player/' + ('pause' if action == 'pause' else 'play') + '?' + urlencode(params))
            elif action in {'next', 'previous'}:
                self.api('POST', '/me/player/' + action + '?' + urlencode(params))
                return result('Spotify accepted the ' + action + '-track request.')
            elif action == 'volume':
                if not device.get('supports_volume', True):
                    raise SpotifyError('This Spotify device does not support API volume control.')
                self.api('PUT', '/me/player/volume?' + urlencode({**params, 'volume_percent': volume}))
                return result(f'Spotify accepted volume {volume} percent.')
            # A 204 acknowledges the command; it does not prove playback started.
            for _ in range(3):
                self.sleep(0.5)
                state = self.state()
                if state.get('device', {}).get('id') != device['id']:
                    continue
                if action == 'pause' and state.get('is_playing') is False:
                    return result('Spotify paused.', True)
                if state.get('is_playing') and (uri is None or (state.get('item') or {}).get('uri') == uri):
                    return result('Spotify is playing ' + (label if uri else safe_text((state.get('item') or {}).get('name', 'the current track'))) + '.', True)
            return result('Spotify accepted the request, but the requested playback state was not confirmed.')
        except SpotifyError as error:
            return PlaybackResult(False, error=str(error))
