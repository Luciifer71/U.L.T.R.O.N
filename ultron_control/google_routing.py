"""Bounded, deterministic routing for read-only account questions.

No network calls, model calls or remote message content belong in this layer.
Unknown personal-account requests get clarification rather than invented access claims.
"""
import re

MAX_REQUEST_LENGTH = 4096
DOMAIN = re.compile(r'\b(?:emails?|mail|gmail|inbox|calendar|appointments?)\b')
MUTATIONS = re.compile(r'\b(?:send|delete|remove|forward|reply|archive|unsubscribe|mark|create|schedule|cancel|reschedule|move|invite)\b')
WORDS = set('check read show give me what whats is are any my i have do has got the a an '
            'latest later recent new unread important upcoming email emails mail gmail inbox '
            'calendar events appointments update updates today for on about of brief briefing '
            'summarize summary tell update and both please you can could would will there '
            'with to know let see get'.split())


def classify_request(prompt):
    if not isinstance(prompt, str) or len(prompt) > MAX_REQUEST_LENGTH:
        return None
    # Quoted examples, hypotheticals and negation are not account-read consent.
    if any(c in prompt for c in ('"', '“', '”', '`')):
        return None
    text = prompt.lower().replace('’', "'")
    if re.search(r"\b(?:not|never|dont|don't|stop|if|hypothetically|example|said|say|quote)\b", text):
        return None
    text = text.replace("what's", "what is")
    if re.search(r"'[^']+'", text):
        return None
    text = re.sub(r"[^a-z0-9 ]", ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'^(?:(?:hey ultron|okay|ok|please) )+', '', text)
    if text in {'my updates', 'give me my updates'}:
        return 'all'
    if not DOMAIN.search(text):
        # Preserve the existing appointment/event shortcut.
        if not re.fullmatch(r'(?:check|show|give me|what are)(?: my)? (?:upcoming )?events(?: today)?', text):
            return None
    else:
        personal = bool(re.search(r'\b(?:my|me|i)\b', text))
        request = bool(re.match(r'(?:can you|could you|would you|please|check|read|show|give|brief|summarize|tell|update|any|are there|is there|do i|have i|what)', text))
        shorthand = bool(re.fullmatch(r'(?:email|mail|calendar) updates?', text))
        if not (personal or request or shorthand):
            return None
        if MUTATIONS.search(text):
            return 'unsupported'
    tokens = set(text.split())
    if tokens - WORDS:
        return 'clarify'
    mail = bool(re.search(r'\b(?:emails?|mail|gmail|inbox)\b', text))
    calendar = bool(re.search(r'\b(?:calendar|events|appointments?)\b', text))
    return 'all' if mail and calendar else 'mail' if mail else 'calendar'


def route_request(prompt):
    """Includes explicit non-executing replies for unsupported/unclear requests."""
    return classify_request(prompt)


def request_kind(prompt):
    """Compatibility API: only supported cached reads count as read requests."""
    kind = classify_request(prompt)
    return kind if kind in {'mail', 'calendar', 'all'} else None
