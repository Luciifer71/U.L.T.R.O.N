"""Bounded YouTube playback in an isolated browser; no paid API or downloads."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, urlencode, urlparse

from ultron.control.request_planning import REQUEST_PREFIX


def playback_plan(prompt):
    if not isinstance(prompt, str) or len(prompt) > 1000:
        return None
    match = re.fullmatch(REQUEST_PREFIX + r"play\s+(.+?)\s+on\s+youtube(?:\s+for me)?[.!?]*",
                         prompt.strip(), re.I)
    if not match:
        return None
    query = match.group(1).strip()
    if (len(query) > 200 or not words(query) or
            re.search(r'\b(?:then|unless|if|instead)\b|[\r\n]', query, re.I)):
        return None
    return [{'function': {'name': 'play_youtube', 'arguments': {'query': query}}}]


def words(text):
    return set(re.findall(r"[^\W_]+", text.casefold(), re.UNICODE))


def watch_url(url):
    parsed = urlparse(url)
    video = parse_qs(parsed.query).get('v', [''])[0]
    if (parsed.scheme == 'https' and parsed.netloc in {'www.youtube.com', 'youtube.com'}
            and parsed.path == '/watch' and re.fullmatch(r'[A-Za-z0-9_-]{11}', video)):
        return 'https://www.youtube.com/watch?' + urlencode({'v': video})
    return None


def choose_video(query, candidates):
    """Require all requested title/artist words; never treat page text as instructions."""
    required = words(query) - {'by', 'the', 'song', 'music'}
    if not required:
        raise RuntimeError('Please specify a song title and artist.')
    # Artist-channel identity is metadata matching, not proof of ownership.
    artist = re.split(r'\s+by\s+', query, maxsplit=1, flags=re.I)
    artist_key = ''.join(re.findall(r'[^\W_]+', artist[1].casefold())) if len(artist) == 2 else ''
    matches = []
    seen = set()
    for item in candidates[:20]:
        url = watch_url(str(item.get('url', '')))
        title, channel = str(item.get('title', ''))[:300], str(item.get('channel', ''))[:200]
        tokens = words(title + ' ' + channel)
        if not url or url in seen or not required <= tokens:
            continue
        if (words(title) & {'cover', 'karaoke', 'reaction', 'remix', 'live', 'slowed', 'sped'}) - words(query):
            continue
        channel_key = ''.join(re.findall(r'[^\W_]+', channel.casefold()))
        artist_match = bool(artist_key and channel_key in {
            artist_key, artist_key + 'vevo', artist_key + 'official', artist_key + 'topic'})
        official = 'official' in words(title)
        score = (artist_match, official, not bool(words(title) & {'lyrics', 'lyric'}))
        seen.add(url)
        matches.append((score, url, title))
    if not matches:
        raise RuntimeError('No confident title/artist match found. Please give the exact song and artist.')
    # Stable sorting preserves YouTube result order, never video-ID order.
    matches.sort(key=lambda item: item[0], reverse=True)
    if len(matches) > 1 and matches[0][0] == matches[1][0]:
        # Multiple official uploads by the explicitly requested artist are an
        # acceptable default version. Unknown-channel ties still need clarity.
        if not (matches[0][0][0] and matches[0][0][1]):
            raise RuntimeError('Several videos match without a clear artist upload. Please specify the version.')

    return matches[0][1], matches[0][2]


# Only fixed scripts execute. User queries are URL-encoded, never interpolated into JS.
RESULTS_JS = """() => Array.from(document.querySelectorAll('ytd-video-renderer')).slice(0,20).map(row => ({
    title: row.querySelector('a#video-title')?.textContent?.trim() || '',
    url: row.querySelector('a#video-title')?.href || '',
    channel: row.querySelector('ytd-channel-name')?.textContent?.trim() || ''
}))"""
STATE_JS = """() => {
    const v = document.querySelector('video');
    return {url: location.href, ad: !!document.querySelector('.ad-showing'),
        time: v?.currentTime || 0, paused: v ? v.paused : true,
        muted: v ? v.muted : true, volume: v?.volume || 0,
        ready: v?.readyState || 0, ended: v ? v.ended : false};
}"""


def playback_verified(before, after, expected):
    return (watch_url(before.get('url', '')) == expected == watch_url(after.get('url', ''))
            and all(not s.get('ad', True) and not s.get('paused', True)
                    and not s.get('muted', True) and not s.get('ended', True)
                    and s.get('volume', 0) > 0 and s.get('ready', 0) >= 2
                    for s in (before, after))
            and after.get('time', 0) > before.get('time', 0) + 0.2)


@dataclass
class PlaybackResult:
    success: bool
    message: str = ''
    error: str | None = None
    data: dict = field(default_factory=dict)


class YouTubePlayback:
    def __init__(self):
        self.context = None
        self.driver = None
        self.page = None
        self.lock = asyncio.Lock()

    async def _page(self):
        if self.page is not None and not self.page.is_closed():
            return self.page
        await self.close()
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError('YouTube playback needs setup: run scripts/windows/setup-youtube-playback.cmd once.') from None
        channel = os.environ.get('ULTRON_BROWSER_CHANNEL', 'msedge').strip().lower()
        if channel not in {'chrome', 'msedge'}:
            raise RuntimeError('ULTRON_BROWSER_CHANNEL must be chrome or msedge.')
        self.driver = await async_playwright().start()
        root = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local/share')) / 'Ultron' / 'youtube-browser'
        if channel == 'chrome':
            root = root.with_name('youtube-browser-chrome')
        try:
            self.context = await self.driver.chromium.launch_persistent_context(
                str(root), channel=channel, headless=False, timeout=20000, chromium_sandbox=True)
            self.context.set_default_timeout(10000)
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            return self.page
        except Exception:
            await self.close()
            raise RuntimeError('Could not open the selected Ultron browser with sandboxing enabled. Check browser installation and policies.') from None

    async def play(self, query):
        async with self.lock:
            try:
                async with asyncio.timeout(60):
                    page = await self._page()
                    await page.goto('https://www.youtube.com/results?' + urlencode({'search_query': query}),
                                    wait_until='domcontentloaded', timeout=20000)
                    if urlparse(page.url).hostname not in {'www.youtube.com', 'youtube.com'}:
                        raise RuntimeError('YouTube requires consent or sign-in in the Ultron browser window.')
                    try:
                        await page.locator('ytd-video-renderer a#video-title').first.wait_for()
                    except Exception:
                        raise RuntimeError('YouTube results are unavailable. Check consent, sign-in, network, or page changes.') from None
                    target, title = choose_video(query, await page.evaluate(RESULTS_JS))
                    await page.goto(target, wait_until='domcontentloaded', timeout=20000)
                    await page.locator('video').first.wait_for()
                    # Attempt normal playback, without changing mute or volume.
                    await page.evaluate("() => { const v = document.querySelector('video'); if (v) v.play().catch(() => {}); }")
                    for _ in range(12):
                        before = await page.evaluate(STATE_JS)
                        await asyncio.sleep(1)
                        after = await page.evaluate(STATE_JS)
                        if playback_verified(before, after, target):
                            return PlaybackResult(True, data={
                                'state': 'verified', 'verification': {'playing': True},
                                'target': target,
                                'verificationReason': 'Requested video time advanced, unmuted, outside ads; speaker audibility unverified.'})
                    raise RuntimeError('Playback was not verified. Check the Ultron YouTube window for ads, consent, muted audio, or a blocked Play button.')
            except asyncio.CancelledError:
                await self.close()
                raise
            except TimeoutError:
                await self.close()
                return PlaybackResult(False, error='YouTube playback timed out; the Ultron browser was closed.')
            except RuntimeError as error:
                return PlaybackResult(False, error=str(error))
            except Exception:
                return PlaybackResult(False, error='YouTube browser control failed. Playback was not verified.')

    async def close(self):
        context, driver = self.context, self.driver
        self.context = self.driver = self.page = None
        try:
            if context:
                await context.close()
        finally:
            if driver:
                await driver.stop()
