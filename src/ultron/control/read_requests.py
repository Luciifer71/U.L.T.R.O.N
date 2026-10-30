"""Bounded composition of read-only facts; no action execution or model calls."""
import re

from ultron.control.google_routing import route_request
from ultron.control.intent_guard import local_information_kind
from ultron.control.local_facts import capabilities_reply
from ultron.control.system_info import collect_telemetry, format_telemetry, format_uptime


def read_request_kinds(prompt):
    if not isinstance(prompt, str) or len(prompt) > 4096:
        return None
    if re.search(r'\b(?:not|never|dont|don\x27t|if|example|quote)\b', prompt, re.I) or any(c in prompt for c in ('"', '`', '“', '”')):
        return None
    text = prompt.strip()
    # Only leading addresses are removed. Never alter an application/file target.
    text = re.sub(r'^(?:(?:hey|hello)\s+ultron[\s,.!?]*)+', '', text, flags=re.I)
    if not text and prompt.strip():
        return ('greeting',)
    text = re.sub(r'^(?:(?:okay|ok|please|can you|could you)[\s,]+)+', '', text, flags=re.I)
    parts = re.split(r'\s+(?:as well as|and also|and|also)\s+', text, flags=re.I)
    if len(parts) > 4:
        return None
    kinds = []
    for part in parts:
        kind = local_information_kind(part)
        if kind not in {'telemetry', 'uptime', 'capabilities'}:
            kind = route_request(part)
            if kind:
                kind = 'google-' + kind
        if not kind or kind in {'clock', 'date', 'disk', 'health', 'stack'}:
            return None
        if kind not in kinds:
            kinds.append(kind)
    return tuple(kinds) if kinds else None


def read_request_reply(kinds, google):
    parts = []
    telemetry = None
    for kind in kinds:
        try:
            if kind.startswith('google-'):
                reply = google.spoken_reply(kind.removeprefix('google-'))
            elif kind == 'capabilities':
                reply = capabilities_reply()
            elif kind == 'greeting':
                reply = "I'm listening. What would you like me to do?"
            else:
                if telemetry is None:
                    telemetry = collect_telemetry()
                reply = format_uptime(telemetry) if kind == 'uptime' else format_telemetry(telemetry)
        except Exception:
            # Failure of one read must not suppress other requested facts.
            reply = ('Google updates' if kind.startswith('google-') else 'System information') + ' are unavailable right now.'
        parts.append(reply)
    return ' '.join(parts)
