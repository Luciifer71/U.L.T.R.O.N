"""Bounded music commands; no inference or remote text becomes an action."""
import re
from ultron.control.request_planning import REQUEST_PREFIX
from ultron.control.youtube_playback import playback_plan


def spotify_request(prompt, *, connected):
    if not connected or not isinstance(prompt, str) or len(prompt) > 1000:
        return None
    text = prompt.strip().rstrip('.!?')
    # References are not titles: do not search Spotify for a song called "now".
    generic = r'play (?:a song|(?:the )?(?:song|music|it|that|this))(?: now)?(?: on spotify)?(?: for me)?'
    if re.fullmatch(REQUEST_PREFIX + r'(?:open spotify and )?' + generic, text, re.I):
        return {'action': 'clarify'}
    # A bounded compound request: opening Spotify is explicit, as is playback.
    compound = re.fullmatch(REQUEST_PREFIX + r'open spotify and (?:search for (.+?) and play it|play (.+))', text, re.I)
    if compound:
        query = compound[1] or compound[2]
        plan = playback_plan('play ' + query + ' on Spotify')
        if plan:
            return {'action': 'play', 'query': plan[0]['function']['arguments']['query'], 'open_first': True}
        return {'action': 'clarify'}
    plan = playback_plan(prompt)
    if plan:
        if re.search(r'\bon youtube(?:\s+for me)?[.!?]*$', prompt.strip(), re.I):
            return None
        return {'action': 'play', 'query': plan[0]['function']['arguments']['query']}
    text = prompt.strip().rstrip('.!?').lower()
    controls = {
        'pause spotify': 'pause', 'pause the music': 'pause',
        'resume spotify': 'resume', 'resume the music': 'resume',
        'next song': 'next', 'next track': 'next', 'skip this song': 'next',
        'previous song': 'previous', 'previous track': 'previous',
        'what is playing on spotify': 'status', "what's playing on spotify": 'status',
        'what song is playing': 'status',
    }
    for phrase, action in controls.items():
        if re.fullmatch(REQUEST_PREFIX + re.escape(phrase), text, re.I):
            return {'action': action}
    volume = re.fullmatch(REQUEST_PREFIX + r'(?:set )?(?:spotify volume|(?:the )?volume (?:of|on|for) spotify) (?:to )?(\d{1,3})(?:\s*(?:percent|%))?(?: for me)?', text, re.I)
    if volume:
        return {'action': 'volume', 'volume': int(volume[1])}
    queued = re.fullmatch(REQUEST_PREFIX + r'queue (.+?)(?: on spotify)?', prompt.strip().rstrip('.!?'), re.I)
    if queued:
        query_plan = playback_plan('play ' + queued[1] + ' on Spotify')
        if query_plan:
            return {'action': 'queue', 'query': query_plan[0]['function']['arguments']['query']}
    return None
