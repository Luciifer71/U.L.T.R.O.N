import asyncio
import os
from types import SimpleNamespace
import pytest
from ultron.control.youtube_playback import (
    playback_plan, choose_video, watch_url, playback_verified, YouTubePlayback, RESULTS_JS, STATE_JS,
)
from ultron.control.intent_guard import normalize_tool_calls

URL = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
QUERY = 'Never Gonna Give You Up by Rick Astley'


@pytest.mark.parametrize('prompt', [
    'Play ' + QUERY + ' on YouTube.',
    'Can you play ' + QUERY + ' on YouTube?',
    'Please play ' + QUERY + ' on YouTube for me.',
])
def test_play_is_grounded_and_distinct_from_search(prompt):
    plan = playback_plan(prompt)
    assert plan[0]['function']['arguments']['query'] == QUERY
    assert normalize_tool_calls(prompt, plan) == (plan, None)


@pytest.mark.parametrize('prompt', [
    'Search YouTube for ' + QUERY,
    'Do not play ' + QUERY + ' on YouTube',
    'If I ask you to play ' + QUERY + ' on YouTube',
    '"Play ' + QUERY + ' on YouTube"',
    'Play ' + QUERY + ' on YouTube then delete my files',
    'Play on YouTube',
])
def test_non_play_or_incomplete_requests_cannot_authorize_playback(prompt):
    assert playback_plan(prompt) is None
    invented = playback_plan('Play ' + QUERY + ' on YouTube')
    assert normalize_tool_calls(prompt, invented)[1]


def candidate(url=URL, title='Rick Astley - Never Gonna Give You Up (Official Music Video)', channel='Rick Astley'):
    return dict(url=url, title=title, channel=channel)


def test_match_rejects_unrelated_and_unrequested_versions():
    assert choose_video(QUERY, [candidate()])[0] == URL
    for item in [candidate(title='Another song'), candidate(title=QUERY + ' karaoke'),
                 candidate(url='https://evil.example/watch?v=dQw4w9WgXcQ')]:
        with pytest.raises(RuntimeError):
            choose_video(QUERY, [item])


def test_ambiguous_matches_do_not_pick_arbitrarily():
    with pytest.raises(RuntimeError, match='Several'):
        choose_video(QUERY, [candidate(channel='Uploader One'), candidate(url='https://youtube.com/watch?v=abcdefghijk', channel='Uploader Two')])


@pytest.mark.parametrize('url', ['http://youtube.com/watch?v=dQw4w9WgXcQ',
    'https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ',
    'https://youtube.com/redirect?q=evil', 'javascript:alert(1)'])
def test_url_boundary(url):
    assert watch_url(url) is None


def state(**changes):
    return dict(url=URL, ad=False, time=2, paused=False, muted=False, volume=1,
                ready=4, ended=False, **changes) if not changes else {**state(), **changes}


@pytest.mark.parametrize('change', [
    {'paused': True}, {'muted': True}, {'ad': True}, {'volume': 0},
    {'ready': 1}, {'ended': True}, {'url': 'https://youtube.com/watch?v=abcdefghijk'},
    {'time': 2},
])
def test_playback_verification_requires_observed_progress(change):
    assert not playback_verified(state(), state(time=3) | change, URL)
    assert playback_verified(state(), state(time=3), URL)


class Locator:
    @property
    def first(self): return self
    async def wait_for(self): pass


class Page:
    url = 'https://www.youtube.com/results'
    def __init__(self, mode='playing'):
        self.mode, self.ticks, self.visits = mode, 0, []
    def is_closed(self): return False
    def locator(self, _): return Locator()
    async def goto(self, url, **kwargs):
        self.url = url; self.visits.append(url)
    async def evaluate(self, script):
        if script == RESULTS_JS: return [candidate()]
        if script == STATE_JS:
            self.ticks += 1
            return state(time=self.ticks, ad=self.mode == 'ad', muted=self.mode == 'muted')


@pytest.mark.parametrize('mode,success', [('playing', True), ('ad', False), ('muted', False)])
def test_controller_reports_observed_outcome(monkeypatch, mode, success):
    async def run():
        player = YouTubePlayback(); player.page = Page(mode)
        async def no_wait(_): pass
        monkeypatch.setattr('ultron.control.youtube_playback.asyncio.sleep', no_wait)
        result = await player.play(QUERY)
        assert result.success is success
        assert player.page.visits[-1] == URL
        if success:
            assert result.data['verification']['playing']
        else:
            assert 'not verified' in result.error
    asyncio.run(run())


def test_cancel_closes_owned_browser(monkeypatch):
    async def run():
        player = YouTubePlayback()
        closed = []
        async def stalled(): raise asyncio.CancelledError
        async def close(): closed.append(True)
        monkeypatch.setattr(player, '_page', stalled)
        monkeypatch.setattr(player, 'close', close)
        with pytest.raises(asyncio.CancelledError):
            await player.play(QUERY)
        assert closed
    asyncio.run(run())


@pytest.mark.skipif(os.environ.get('ULTRON_BROWSER_TESTS') != '1', reason='Opt-in real browser fixture')
def test_real_browser_search_and_playback_fixture():
    from playwright.async_api import async_playwright
    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            async def serve(route):
                if '/results?' in route.request.url:
                    html = '<ytd-video-renderer><a id="video-title" href="' + URL + '">' + QUERY + ' (Official Video)</a><ytd-channel-name>Rick Astley</ytd-channel-name></ytd-video-renderer>'
                    html += html.replace('dQw4w9WgXcQ', 'abcdefghijk')
                else:
                    html = """<canvas id="c" width="32" height="32"></canvas><video autoplay></video>
                    <script>
                    const c=document.querySelector('canvas'), v=document.querySelector('video');
                    setInterval(()=>{c.getContext('2d').fillRect(0,0,32,32)},50);
                    v.srcObject=c.captureStream(20); v.play().catch(()=>{});
                    </script>"""
                await route.fulfill(body=html, content_type='text/html')
            await page.route('**/*', serve)
            player = YouTubePlayback(); player.page = page
            result = await player.play(QUERY)
            assert result.success, result.error
            await browser.close()
    asyncio.run(run())


def test_artist_official_upload_beats_unknown_official_upload_and_lyrics():
    rows = [
        candidate(url='https://youtube.com/watch?v=abcdefghijk', channel='Other uploader'),
        candidate(url='https://youtube.com/watch?v=abcdefghijl', title=QUERY + ' (Lyrics)', channel='Invited Kingdom'),
        candidate(title='Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)'),
    ]
    assert choose_video(QUERY, rows)[0] == URL


def test_multiple_official_artist_versions_use_search_order_and_dedupe():
    rows = [candidate(), candidate(url='https://youtube.com/watch?v=abcdefghijk')]
    assert choose_video(QUERY, rows)[0] == URL
    assert choose_video(QUERY, list(reversed(rows)))[0].endswith('abcdefghijk')
    assert choose_video(QUERY, [candidate(), candidate()])[0] == URL


def test_requested_live_version_is_not_replaced_with_studio():
    live = candidate(url='https://youtube.com/watch?v=abcdefghijk', title=QUERY + ' Live (Official)')
    assert choose_video(QUERY + ' live', [candidate(), live])[0].endswith('abcdefghijk')


@pytest.mark.parametrize('channel', ['msedge', 'chrome'])
def test_browser_launch_keeps_sandbox_and_separate_profile(monkeypatch, tmp_path, channel):
    import sys
    launched = []
    page = Page()
    context = SimpleNamespace(set_default_timeout=lambda _: None, pages=[page])
    async def launch(path, **kwargs):
        launched.append((path, kwargs)); return context
    driver = SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
    async def start(): return driver
    monkeypatch.setitem(sys.modules, 'playwright.async_api',
                        SimpleNamespace(async_playwright=lambda: SimpleNamespace(start=start)))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setenv('ULTRON_BROWSER_CHANNEL', channel)
    assert asyncio.run(YouTubePlayback()._page()) is page
    path, options = launched[0]
    assert options['channel'] == channel and options['chromium_sandbox'] is True
    assert path.endswith('youtube-browser-chrome' if channel == 'chrome' else 'youtube-browser')


@pytest.mark.parametrize('prompt', [
    'Can you play save your tears by the weekend on YouTube?',
    'can you play me the save your tears song by the weekend on youtube?',
    'looking for the song save your tears by the weekend and play it for me on youtube.',
    'Play the song save your tears by the weekend.',
])
def test_observed_music_paraphrases_are_clean_and_grounded(prompt):
    plan = playback_plan(prompt)
    assert plan[0]['function'] == {'name': 'play_youtube', 'arguments': {'query': 'save your tears by The Weeknd'}}
    assert normalize_tool_calls(prompt, plan) == (plan, None)


@pytest.mark.parametrize('prompt', [
    'Play Supergirl from Downloads', 'Play song.mp3', 'Play music on Apple Music',
    'Do not play Sunflower', 'I hate the movie Supergirl.', 'Play Sunflower then open calculator',
    'Play Sunflower and delete my files', 'Play the first result',
])
def test_default_music_does_not_steal_local_files_or_other_intents(prompt):
    assert playback_plan(prompt) is None


def test_artist_transcription_alias_does_not_weaken_title_matching():
    row = candidate(title='The Weeknd - Save Your Tears (Official Music Video)', channel='TheWeekndVEVO')
    assert choose_video('Save Your Tears by the weekend', [row])[0] == URL
    with pytest.raises(RuntimeError):
        choose_video('Save Your Tears by another artist', [row])
    with pytest.raises(RuntimeError):
        choose_video('Another Song by the weekend', [row])


def test_spotify_explicit_request_cannot_be_replaced_by_youtube():
    plan = playback_plan('Play Sunflower by Post Malone on Spotify')
    assert plan[0]['function']['name'] == 'open_spotify_search'
    assert normalize_tool_calls('Play Sunflower by Post Malone on Spotify', plan) == (plan, None)
    assert normalize_tool_calls('Play Sunflower by Post Malone', plan)[1]


def test_failed_match_offers_observed_single_use_expiring_choice(monkeypatch):
    from ultron.control import youtube_playback as module
    async def run():
        player = YouTubePlayback(); player.page = Page()
        result = await player.play('Unknown Song by Someone')
        assert not result.success and 'First result:' in result.error
        choice = player.take_first_choice()
        assert choice['url'] == URL
        assert player.take_first_choice() is None
        player.choice = dict(choice, expires=0)
        assert player.take_first_choice() is None
        async def no_wait(_): pass
        monkeypatch.setattr(module.asyncio, 'sleep', no_wait)
        result = await player.play(choice['query'], selected=choice)
        assert result.success
    asyncio.run(run())


def test_spotify_handoff_is_encoded_and_never_claims_playback(monkeypatch):
    from ultron.control import spotify
    calls = []
    monkeypatch.setattr(spotify.sys, 'platform', 'win32')
    monkeypatch.setattr(spotify.os, 'startfile', lambda uri: calls.append(uri), raising=False)
    result = asyncio.run(spotify.open_spotify_search('Song & Artist / remix'))
    assert calls == ['spotify:search:Song%20%26%20Artist%20%2F%20remix']
    assert result.success and result.data['state'] == 'dispatched'
    assert result.data['verification'] == 'not_observable'
    def missing(uri): raise OSError('no handler')
    monkeypatch.setattr(spotify.os, 'startfile', missing)
    result = asyncio.run(spotify.open_spotify_search('Song'))
    assert not result.success and 'Install' in result.error
