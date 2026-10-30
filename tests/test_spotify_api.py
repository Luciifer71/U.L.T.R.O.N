import asyncio
import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import pytest
from ultron.control import spotify_api as api
from ultron.control.spotify_routing import spotify_request
from ultron.cli.spotify_connect import callback_code

URI = 'spotify:track:' + 'A' * 22
DEVICE = {'id': 'laptop', 'name': 'Laptop', 'is_active': True, 'supports_volume': True}
ROW = {'uri': URI, 'name': 'Sunflower', 'artists': [{'name': 'Post Malone'}, {'name': 'Swae Lee'}]}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))


def test_pkce_and_callback_do_not_accept_missing_or_wrong_state():
    verifier, challenge = api.pkce_pair()
    assert 43 <= len(verifier) <= 128 and len(challenge) == 43
    url = api.authorization_url('a' * 32, 'state', challenge)
    args = parse_qs(urlparse(url).query)
    assert args['redirect_uri'] == [api.REDIRECT_URI]
    assert args['code_challenge_method'] == ['S256']
    assert 'client_secret' not in args and verifier not in url
    assert callback_code('/callback?state=state&code=code', 'state') == 'code'
    for path in ['/callback?code=code', '/callback?state=bad&code=code',
                 '/callback?state=state&state=state&code=code',
                 '/callback?state=state&code=a&code=b', '/else?state=state&code=code',
                 '/callback?state=state&error=access_denied']:
        with pytest.raises(api.SpotifyError): callback_code(path, 'state')


def test_refresh_retains_refresh_token_and_closes_scope_gap(monkeypatch):
    store = {'value': json.dumps(dict(client_id='a'*32, access_token='old', refresh_token='refresh',
                                    scope=sorted(api.SCOPES), expires_at=0))}
    vault = SimpleNamespace(get_password=lambda *a: store['value'],
                            set_password=lambda *a: store.update(value=a[-1]))
    monkeypatch.setattr(api, 'vault', lambda: vault)
    calls = []
    def request(method, url, **kw):
        calls.append((method, url, kw))
        return 200, {'access_token': 'new', 'expires_in': 3600}
    client = api.SpotifyClient(request=request)
    assert client._token() == 'new'
    assert json.loads(store['value'])['refresh_token'] == 'refresh'
    assert len(calls) == 1 and 'client_secret' not in calls[0][2]['data']
    assert client._token() == 'new' and len(calls) == 1
    with pytest.raises(api.SpotifyError):
        api.token_record('id', {'access_token': 'a', 'refresh_token': 'r', 'scope': '', 'expires_in': 3600})


@pytest.mark.parametrize('status,text', [(403,'Premium'), (404,'device'), (429,'rate-limiting'), (500,'rejected')])
def test_http_errors_are_bounded_and_redacted(monkeypatch, status, text):
    calls = []
    def request(*a, **kw): calls.append(a); return status, {'secret': 'DO_NOT_PRINT'}
    client = api.SpotifyClient(request=request)
    monkeypatch.setattr(client, '_token', lambda **kw: 'token')
    with pytest.raises(api.SpotifyError, match=text) as exc: client.api('GET', '/me/player')
    assert 'DO_NOT_PRINT' not in str(exc.value) and len(calls) == 1


def test_401_refreshes_once_not_forever(monkeypatch):
    requests, tokens = [], []
    def request(*a, **kw): requests.append(kw); return 401, {}
    client = api.SpotifyClient(request=request)
    def token(**kw): tokens.append(kw); return 'token'
    monkeypatch.setattr(client, '_token', token)
    with pytest.raises(api.SpotifyError, match='expired'): client.api('GET', '/me/player')
    assert len(requests) == 2 and tokens == [{}, {'force': True}]


def fake_client(monkeypatch, *, state=None, rows=None, devices=None):
    client = api.SpotifyClient(sleep=lambda _: None)
    calls = []
    def call(method, path, **kw):
        calls.append((method, path, kw))
        if path == '/me/player/devices': return {'devices': [DEVICE] if devices is None else devices}
        if path.startswith('/search?'): return {'tracks': {'items': [ROW] if rows is None else rows}}
        if method == 'GET' and path == '/me/player':
            return state if state is not None else {'device': DEVICE, 'item': ROW, 'is_playing': True}
        return {}
    monkeypatch.setattr(client, 'api', call)
    return client, calls


def test_play_uses_track_id_and_verifies_actual_device_and_track(monkeypatch):
    client, calls = fake_client(monkeypatch)
    result = client.perform('play', query='Sunflower by Post Malone')
    assert result.success and result.data['state'] == 'verified'
    sent = next(c for c in calls if c[0] == 'PUT')
    assert sent[2]['body'] == {'uris': [URI]} and 'device_id=laptop' in sent[1]
    assert 'Post Malone' in result.message


@pytest.mark.parametrize('state', [
    {}, {'device': DEVICE, 'item': ROW, 'is_playing': False},
    {'device': {'id': 'phone'}, 'item': ROW, 'is_playing': True},
    {'device': DEVICE, 'item': {'uri': 'wrong'}, 'is_playing': True},
])
def test_acknowledgement_never_becomes_false_playback_claim(monkeypatch, state):
    client, _ = fake_client(monkeypatch, state=state)
    result = client.perform('play', query='Sunflower by Post Malone')
    assert result.success and result.data['state'] == 'dispatched'
    assert 'not confirmed' in result.message


def test_no_device_or_ambiguous_track_never_sends_play(monkeypatch):
    client, calls = fake_client(monkeypatch, devices=[])
    assert not client.perform('play', query='Sunflower by Post Malone').success
    assert not any(c[0] == 'PUT' for c in calls)
    client, calls = fake_client(monkeypatch, rows=[ROW, {**ROW, 'name':'Sunflower', 'artists':[{'name':'Other Artist'}]}])
    assert not client.perform('play', query='Sunflower').success
    assert not any(c[0] == 'PUT' for c in calls)


def test_alias_matches_metadata_but_unrequested_remix_does_not(monkeypatch):
    row = {**ROW, 'name':'Save Your Tears', 'artists':[{'name':'The Weeknd'}]}
    client, _ = fake_client(monkeypatch, rows=[row])
    assert client.find_track('Save Your Tears by weekend')[0] == URI
    client, _ = fake_client(monkeypatch, rows=[{**row,'name':'Save Your Tears Remix'}])
    with pytest.raises(api.SpotifyError): client.find_track('Save Your Tears by weekend')


def test_controls_queue_and_volume_are_scoped(monkeypatch):
    client, calls = fake_client(monkeypatch, state={'device': DEVICE, 'is_playing': False})
    assert client.perform('pause').message == 'Spotify paused.'
    assert client.perform('queue', query='Sunflower by Post Malone').data['state'] == 'dispatched'
    assert client.perform('volume', volume=40).success
    count = len(calls)
    assert not client.perform('volume', volume=101).success and len(calls) == count
    assert not client.perform('delete').success


@pytest.mark.parametrize('prompt,action', [
    ('Play Sunflower by Post Malone.', 'play'), ('Play Sunflower on Spotify', 'play'),
    ('Pause Spotify', 'pause'), ('Resume the music', 'resume'), ('Next song', 'next'),
    ('What song is playing?', 'status'), ('Set Spotify volume to 40 percent', 'volume'),
    ('Queue Sunflower by Post Malone on Spotify', 'queue'),
])
def test_grounded_routing(prompt, action):
    assert spotify_request(prompt, connected=True)['action'] == action
    assert spotify_request(prompt, connected=False) is None


@pytest.mark.parametrize('prompt', [
    'Play Sunflower on YouTube', 'Play Supergirl from Downloads', 'Do not pause Spotify',
    'If I say pause Spotify', '"Pause Spotify"', 'Pause Spotify then delete files',
    'Queue Sunflower and delete files', 'Set Spotify volume to 40 and open Notion',
])
def test_music_routing_preserves_service_scope_and_negation(prompt):
    assert spotify_request(prompt, connected=True) is None


def test_preferred_device_must_still_exist(monkeypatch):
    client, _ = fake_client(monkeypatch)
    assert client.select_device('Laptop') == 'Laptop'
    assert client.device()['id'] == 'laptop'
    monkeypatch.setattr(client, 'devices', lambda: [])
    with pytest.raises(api.SpotifyError): client.device()


def test_connect_binds_loopback_exchanges_pkce_and_stores_no_token_file(monkeypatch):
    import ultron.cli.spotify_connect as cli
    saved, requests, urls = [], [], []
    class Server:
        def __init__(self, address, handler):
            assert address == ('127.0.0.1', 8888); self.handler = handler
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def handle_request(self):
            from io import BytesIO
            params = parse_qs(urlparse(urls[0]).query)
            handler = object.__new__(self.handler)
            handler.headers = {'Host': '127.0.0.1:8888'}
            handler.path = '/callback?state=' + params['state'][0] + '&code=code'
            handler.wfile = BytesIO()
            handler.send_response = lambda *a: None
            handler.send_header = lambda *a: None
            handler.end_headers = lambda: None
            handler.do_GET()
    monkeypatch.setattr(cli, 'HTTPServer', Server)
    monkeypatch.setattr(cli.webbrowser, 'open', lambda url: urls.append(url) or True)
    def request(*a, **kw):
        requests.append(kw)
        return 200, dict(access_token='ACCESS_SECRET', refresh_token='REFRESH_SECRET', expires_in=3600, scope=' '.join(api.SCOPES))
    monkeypatch.setattr(cli, '_request', request)
    monkeypatch.setattr(cli, 'save_record', saved.append)
    cli.connect('a' * 32)
    assert saved[0]['access_token'] == 'ACCESS_SECRET'
    assert requests[0]['data']['redirect_uri'] == api.REDIRECT_URI
    assert 'code_verifier' in requests[0]['data'] and 'client_secret' not in requests[0]['data']
    assert api.configured()
    for file in api.private_dir().iterdir():
        assert 'SECRET' not in file.read_text()


@pytest.mark.parametrize('prompt,expected', [
    ('Can you set the volume of Spotify to 40%?', {'action': 'volume', 'volume': 40}),
    ('Set the volume on Spotify to 40 percent', {'action': 'volume', 'volume': 40}),
    ('Open Spotify and search for save your tears by weekend and play it.', {'action': 'play', 'query': 'save your tears by The Weeknd', 'open_first': True}),
    ('Can you open Spotify and play Sunflower by Post Malone?', {'action': 'play', 'query': 'Sunflower by Post Malone', 'open_first': True}),
    ('Can you play the song now?', {'action': 'clarify'}),
    ('Can you open Spotify and play a song?', {'action': 'clarify'}),
    ('Play it now', {'action': 'clarify'}),
    ('Resumes 45.', None),
    ('Do not open Spotify and play Sunflower', None),
    ('If I open Spotify and play Sunflower', None),
    ('Set the volume of Spotify to 40% and delete files', None),
])
def test_live_session_phrasings(prompt, expected):
    assert spotify_request(prompt, connected=True) == expected


def test_device_error_distinguishes_empty_from_ambiguous(monkeypatch):
    client, _ = fake_client(monkeypatch, devices=[])
    with pytest.raises(api.SpotifyError, match='no available playback devices'): client.device()
    client, _ = fake_client(monkeypatch, devices=[dict(DEVICE, is_active=False), dict(DEVICE, id='phone', is_active=False)])
    with pytest.raises(api.SpotifyError, match='Several Spotify devices'): client.device()


def test_support_spotify_check_is_bounded_and_omits_raw_error_output(monkeypatch):
    from ultron.cli import ultron_diagnostics as diagnostics
    monkeypatch.setattr(api, 'configured', lambda: True)
    calls = []
    def run(*a, **kw):
        calls.append(kw)
        return SimpleNamespace(stdout='TOKEN_DO_NOT_COPY', returncode=1)
    monkeypatch.setattr(diagnostics.subprocess, 'run', run)
    report = diagnostics.check_spotify()
    assert report['status'] == 'diagnostic_failed'
    assert 'TOKEN_DO_NOT_COPY' not in json.dumps(report)
    assert calls[0]['timeout'] == 45
    monkeypatch.setattr(diagnostics.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout='{"connection":"ok","available_devices":0}'))
    assert diagnostics.check_spotify()['available_devices'] == 0
