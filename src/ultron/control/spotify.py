"""Free desktop-app handoff, not an OAuth connection or verified playback."""
import asyncio
import os
import subprocess
import sys
from urllib.parse import quote

from ultron.control.youtube_playback import PlaybackResult


def _open_search(query):
    uri = 'spotify:search:' + quote(query, safe='')
    if sys.platform == 'win32':
        os.startfile(uri)
    elif sys.platform == 'darwin':
        subprocess.run(['open', uri], check=True, timeout=10)
    else:
        subprocess.run(['xdg-open', uri], check=True, timeout=10)


async def open_spotify_search(query):
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        return PlaybackResult(False, error='Please give a song title and artist for Spotify.')
    try:
        await asyncio.to_thread(_open_search, query)
    except (OSError, subprocess.SubprocessError):
        return PlaybackResult(False, error='Could not open Spotify search. Install the Spotify desktop app and sign in, or ask to play on YouTube.')
    return PlaybackResult(True, message='Spotify search dispatched; playback not verified.', data={
        'state': 'dispatched', 'verification': 'not_observable',
        'verificationReason': 'The operating system accepted a Spotify search URI. Track playback and account state were not observed.'})
