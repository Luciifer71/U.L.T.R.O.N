"""Local Spotify PKCE sign-in. No client secret or plaintext token files."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import re
import secrets
import time
from urllib.parse import parse_qs, urlparse
import webbrowser

from ultron.control.spotify_api import (
    REDIRECT_URI, SpotifyClient, SpotifyError, _request, authorization_url,
    disconnect, pkce_pair, private_dir, save_record, token_record,
)


def callback_code(path, expected_state):
    parsed = urlparse(path)
    params = parse_qs(parsed.query)
    if parsed.path != '/callback' or len(params.get('state', [])) != 1:
        raise SpotifyError('Invalid Spotify callback.')
    if not hmac.compare_digest(params['state'][0], expected_state):
        raise SpotifyError('Spotify callback state did not match.')
    if 'error' in params:
        raise SpotifyError('Spotify authorization was declined. No connection was saved.')
    codes = params.get('code', [])
    if len(codes) != 1 or not codes[0] or len(codes[0]) > 4096:
        raise SpotifyError('Spotify did not return an authorization code.')
    return codes[0]


def connect(client_id, *, timeout=120):
    if not re.fullmatch(r'[a-fA-F0-9]{32}', client_id):
        raise SpotifyError('Enter the 32-character Client ID from your Spotify app settings.')
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(32)
    received = {}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Callback URLs contain a short-lived authorization code.
        def do_GET(self):
            try:
                if self.headers.get('Host') != '127.0.0.1:8888':
                    raise SpotifyError('Invalid callback host.')
                code = callback_code(self.path, state)
            except SpotifyError:
                self.send_response(400); self.end_headers()
                self.wfile.write(b'Authorization not accepted. Check the Ultron terminal or try again.')
                return
            received['code'] = code
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(b'Authorization received. Return to the Ultron terminal to check completion.')
    class LoopbackServer(HTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(2)
            return connection, address
    try:
        server = LoopbackServer(('127.0.0.1', 8888), Handler)
    except OSError:
        raise SpotifyError('Local port 8888 is unavailable. Close the other app using it and retry.') from None
    with server:
        server.timeout = 1
        print('Opening Spotify authorization. Approve access in your browser. Waiting up to two minutes.', flush=True)
        if not webbrowser.open(authorization_url(client_id, state, challenge)):
            raise SpotifyError('Could not open the browser. Set a default browser and retry.')
        deadline = time.monotonic() + timeout
        while 'code' not in received and time.monotonic() < deadline:
            server.handle_request()
    if 'code' not in received:
        raise SpotifyError('Spotify authorization timed out or was declined. No new connection was saved.')
    status, payload = _request('POST', 'https://accounts.spotify.com/api/token', data={
        'client_id': client_id, 'grant_type': 'authorization_code', 'code': received['code'],
        'redirect_uri': REDIRECT_URI, 'code_verifier': verifier})
    if status != 200:
        raise SpotifyError('Spotify rejected the authorization exchange. Check the Client ID and registered redirect URI, then retry.')
    save_record(token_record(client_id, payload))
    root = private_dir(); root.mkdir(parents=True, exist_ok=True)
    (root / 'device.json').unlink(missing_ok=True)  # Previous account device IDs must not carry over.
    (root / 'enabled').touch()
    print('Spotify authorization saved in Windows Credential Manager. Named songs now default to Spotify. Restart Ultron if running.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['connect', 'doctor', 'devices', 'device', 'disconnect'])
    parser.add_argument('--client-id', help='Spotify app Client ID (not the Client Secret). Prompted if omitted.')
    parser.add_argument('--name', help='Exact device name or ID for the device command.')
    args = parser.parse_args()
    try:
        if args.command == 'connect':
            connect((args.client_id or input('Spotify Client ID: ')).strip())
        elif args.command == 'disconnect':
            disconnect()
            print('Local Spotify authorization removed. Revoke app access in Spotify account settings if desired.')
        elif args.command == 'device':
            if not args.name:
                parser.error('--name is required for device')
            print('Preferred Spotify device:', SpotifyClient().select_device(args.name))
        else:
            client = SpotifyClient()
            devices = client.devices()
            if args.command == 'devices':
                print(json.dumps([{'name': d.get('name'), 'id': d['id'], 'active': d.get('is_active')} for d in devices], indent=2))
            else:
                state = client.state()
                print(json.dumps({'connection': 'ok', 'available_devices': len(devices),
                    'playback_active': bool(state.get('is_playing')),
                    'scope': 'Read-only checks; no track, tokens or account identifiers included.'}, indent=2))
        return 0
    except SpotifyError as error:
        print(str(error))
        return 1
    except (KeyboardInterrupt, EOFError):
        print('Spotify setup cancelled.')
        return 1
    except Exception:
        print('Spotify setup failed. No credentials are included in this message. Check the optional dependencies and Windows Credential Manager.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
