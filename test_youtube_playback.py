import asyncio
import os
from types import SimpleNamespace
import pytest
from ultron_control.youtube_playback import (
    playback_plan, choose_video, watch_url, playback_verified, YouTubePlayback, RESULTS_JS, STATE_JS,
)
from ultron_control.intent_guard import normalize_tool_calls

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
        choose_video(QUERY, [candidate(), candidate(url='https://youtube.com/watch?v=abcdefghijk')])


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
        monkeypatch.setattr('ultron_control.youtube_playback.asyncio.sleep', no_wait)
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
                    html = '<ytd-video-renderer><a id="video-title" href="' + URL + '">' + QUERY + '</a><ytd-channel-name>Rick Astley</ytd-channel-name></ytd-video-renderer>'
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
