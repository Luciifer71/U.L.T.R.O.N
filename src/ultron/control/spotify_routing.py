"""Bounded music commands; no inference or remote text becomes an action."""
import re
from ultron.control.request_planning import REQUEST_PREFIX
from ultron.control.youtube_playback import playback_plan


def spotify_request(prompt, *, connected):
    if not connected or not isinstance(prompt, str) or len(prompt) > 1000:
        return None
    text = prompt.strip().rstrip('.!?').replace('\u2019', "'")
    # Playback controls are checked before song search, so "play the previous
    # song" skips back instead of searching for a track called "the previous song".
    control = control_request(text)
    if control:
        return control
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
    queued = re.fullmatch(REQUEST_PREFIX + r'queue (.+?)(?: on spotify)?', prompt.strip().rstrip('.!?'), re.I)
    if queued:
        query_plan = playback_plan('play ' + queued[1] + ' on Spotify')
        if query_plan:
            return {'action': 'queue', 'query': query_plan[0]['function']['arguments']['query']}
    return None


# Whole-request phrasings only: anything extra ("and delete files", "don't ...",
# "if I say ...") falls through to the normal planner and its validation.
_SONG = r"(?:(?:the |this |current |spotify )?(?:song|track|music|playback))"
_TAIL = r"(?: on spotify| in spotify)?(?: for me)?(?: please)?(?: now| right now)?"
_CONTROLS = (
    ('pause', rf"pause(?: spotify| {_SONG})?|stop(?: spotify| {_SONG}| playing)"),
    ('resume', rf"(?:resume|unpause)(?: spotify| {_SONG}| playing)?|continue(?: spotify| {_SONG}| playing)"
               r"|keep playing|play (?:some |my )?music|play some songs|play something|start (?:the )?music"),
    ('next', rf"(?:skip|next)(?: {_SONG}| one| it)?|(?:play|go to|skip to|switch to|jump to)(?: the)? next(?: song| track| one)?"
             r"|change (?:the )?(?:song|track)"),
    ('previous', r"(?:(?:play|go to|go back to|skip back to|back to|jump to) )?(?:the )?previous(?: song| track| one)?"
                 r"|go back (?:a|one) (?:song|track)|(?:play )?(?:the )?(?:last|previous) (?:song|track) again"),
    ('status', r"(?:tell me )?(?:what|which) (?:spotify )?(?:song|track)(?: is)?(?: currently)? (?:this|playing|is this|is playing)"
               r"|(?:tell me )?what(?:'s| is)(?: currently)? playing|(?:tell me )?what(?:'s| is) this (?:song|track)"
               r"|what am i listening to|(?:tell me )?(?:the )?name of (?:this|the current) (?:song|track)"),
)
_SPOTIFY_VOLUME = r"(?:(?:the )?spotify(?:'s)? volume|(?:the )?volume (?:of|on|for|in) spotify)"


def control_request(text):
    """Map a whole spoken control request to one bounded Spotify action."""
    lowered = text.lower()
    for action, pattern in _CONTROLS:
        if re.fullmatch(REQUEST_PREFIX + rf"(?:{pattern}){_TAIL}", lowered):
            return {'action': action}
    volume = re.fullmatch(
        REQUEST_PREFIX + rf"(?:(?:set|turn|change|put|make) )?(?:{_SPOTIFY_VOLUME}|spotify)(?: to| at)? (\d{{1,3}})"
        r"(?:\s*(?:percent|%))?(?: for me)?(?: please)?", lowered)
    if volume:
        return {'action': 'volume', 'volume': int(volume[1])}
    # Relative changes need "Spotify" in the request: a bare "volume up" stays
    # with the existing system-volume control.
    step = re.fullmatch(
        REQUEST_PREFIX + rf"(?:(?:(?:turn|set|put) )?(?:{_SPOTIFY_VOLUME}|spotify) (up|down)"
        rf"|turn (up|down) (?:{_SPOTIFY_VOLUME}|spotify)|make (?:this |the )?spotify (louder|quieter))"
        r"(?: a (?:bit|little))?(?: for me)?(?: please)?", lowered)
    if step:
        word = next(group for group in step.groups() if group)
        return {'action': 'volume_up' if word in {'up', 'louder'} else 'volume_down'}
    return None
