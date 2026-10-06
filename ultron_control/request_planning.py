"""Complete plans for a deliberately bounded, explicit launch grammar.

No fuzzy recognition, shell commands, or execution happens here. Requests
outside this grammar remain on the model path; ambiguous target lists inside
the grammar require clarification instead of silently dropping a target.
"""
from __future__ import annotations

import re


APPLICATION_ALIASES = {
    "calculator": "Calculator", "calc": "Calculator",
    "file explorer": "File Explorer", "explorer": "File Explorer",
    "task manager": "Task Manager", "taskmgr": "Task Manager",
    "microsoft edge": "Microsoft Edge", "edge": "Microsoft Edge",
    "google chrome": "Google Chrome", "chrome": "Google Chrome",
    "microsoft store": "Microsoft Store", "store": "Microsoft Store",
    "visual studio code": "Visual Studio Code", "vs code": "Visual Studio Code",
    "vscode": "Visual Studio Code", "notion": "Notion",
    "perplexity": "Perplexity", "spotify": "Spotify", "discord": "Discord",
    "notepad": "Notepad", "command prompt": "Command Prompt", "cmd": "Command Prompt",
    "powershell": "PowerShell", "windows terminal": "Windows Terminal",
    "terminal": "Windows Terminal", "firefox": "Firefox", "brave": "Brave",
}
SEARCH_SITES = {"youtube", "google", "bing", "github", "reddit", "duckduckgo"}


def _words(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.casefold()).strip()


def _mentions_target(text: str, target: str) -> bool:
    """Match contiguous whole words, allowing cosmetic name spacing only."""
    target = re.sub(r"\.exe$", "", target.strip(), flags=re.I)
    compact = "".join(_words(target).split())
    if not compact:
        return False
    words = _words(text).split()
    for start in range(len(words)):
        candidate = ""
        for word in words[start:]:
            candidate += word
            if candidate == compact:
                return True
            if len(candidate) >= len(compact):
                break
    return False


def _launch_clauses(prompt: str) -> list[str]:
    pattern = r"\b(?:open|launch)\s+(.+?)(?=\b(?:search|close|terminate|kill|delete|run|execute|type|click|press|download|upload|organize)\b|$)"
    clauses = []
    for match in re.finditer(pattern, prompt, re.I):
        prefix = prompt[:match.start()]
        if re.search(r"(?:don't|do not|never)\s*$", prefix, re.I):
            continue
        # 'how to open Notion' inside a search is query text. A subsequent
        # explicit 'and also open ...' resumes launch instruction parsing.
        if re.search(r"\bsearch\b", prefix, re.I) and not re.search(r"\b(?:and|then|also)\s+(?:(?:also|then)\s+)?$", prefix, re.I):
            continue
        clauses.append(match.group(1))
    return clauses


def validate_application_targets(prompt: str, calls: list[dict]) -> str | None:
    """Reject application names absent from the current request.

    This is a grounding check, not a universal natural-language intent proof.
    Explicit replay is handled separately by the brain's stored replay plan.
    """
    clauses = _launch_clauses(prompt)
    if clauses:
        grounding_text = " ".join(clauses)
    elif re.search(r"\b(?:search|open|launch)\b", prompt, re.I):
        grounding_text = ""
    else:
        grounding_text = prompt
    current = " " + _words(grounding_text) + " "
    planned = set()
    for call in calls:
        function = call.get("function", {})
        if function.get("name") == "activate_protocol":
            protocol = str(function.get("arguments", {}).get("protocol", ""))
            label = protocol.replace("_", " ")
            protocol_request = re.search(
                r"(?:^(?:please\s+|(?:can|could|would) you\s+)?|\b(?:and|then)\s+)"
                r"(?:activate|enable|enter|start|switch to)\s+(?:the\s+)?" + re.escape(label) + r"\b",
                prompt.replace("_", " "), re.I,
            )
            if not label or not protocol_request:
                return "You did not request that protocol activation. Please state the action you want. No actions were started."
        if function.get("name") != "open_application":
            continue
        target = str(function.get("arguments", {}).get("app_name", ""))
        canonical = APPLICATION_ALIASES.get(target.casefold().strip(), target)
        planned.add(canonical.casefold())
        aliases = {canonical, target}
        aliases.update(alias for alias, name in APPLICATION_ALIASES.items() if name.casefold() == canonical.casefold())
        if not any(_mentions_target(current, alias) for alias in aliases):
            return (
                f"The proposed application '{target}' was not named in your current request. "
                "Please state the applications you want to open. No actions were started."
            )
    # Check named catalog applications within explicit launch clauses, while
    # excluding search text. Unknown names still require discovery/clarification.
    requested = set()
    aliases = sorted(APPLICATION_ALIASES, key=len, reverse=True)
    for clause in clauses:
        remaining = _words(clause)
        while remaining:
            found = next((alias for alias in aliases if remaining == alias or remaining.startswith(alias + " ")), None)
            if found:
                requested.add(APPLICATION_ALIASES[found].casefold())
                remaining = remaining[len(found):].lstrip()
            else:
                remaining = remaining.partition(" ")[2]
    missing = sorted(requested - planned)
    if missing:
        return (
            "The plan omitted requested applications: " + ", ".join(missing) + ". "
            "Please repeat the complete application list. No actions were started."
        )
    return None


class PlanClarification(ValueError):
    """An explicit launch list could not be parsed completely."""


def _call(name: str, **arguments) -> dict:
    return {"function": {"name": name, "arguments": arguments}}


def explicit_launch_plan(prompt: str) -> list[dict] | None:
    """Return a complete plan, None for other grammar, or ask for clarification.

    Supports polite open/launch lists followed optionally by an on-site search.
    The entire target list must be consumed. Names in query text are never
    extracted as application targets. Duplicate targets retain user ordering.
    """
    text = re.sub(r"\s+", " ", prompt.strip())
    prefix = re.fullmatch(
        r"(?:(?:ok|okay)[, ]+)?(?:please )?(?:(?:can|could|would) you )?"
        r"(?:do me a favor and )?(?:please )?(?:open|launch) (.+?)[.!?]*",
        text, re.IGNORECASE,
    )
    if not prefix:
        return None
    remainder = prefix.group(1).strip()
    # Conditions, exclusions, sequencing beyond this grammar and quoted
    # discussion require the general planner; never infer them as launches.
    if re.search(r"\b(?:if|unless|except|don't|do not|without|before|after|instead)\b", remainder, re.I):
        return None
    search = re.search(r"\s+and\s+search\s+(?:on\s+)?([a-z]+)\s+(.+)$", remainder, re.I)
    search_call = None
    if search:
        site, query = search.groups()
        if site.lower() not in SEARCH_SITES:
            return None
        query = re.sub(r"^for\s+", "", query, flags=re.I).strip()
        if not query:
            raise PlanClarification("What should I search for?")
        search_call = _call("open_website", target=site.lower(), query=query, count=1)
        remainder = remainder[:search.start()].strip()
    remainder = re.sub(r"\s+(?:for me|please)$", "", remainder, flags=re.I).strip()
    aliases = sorted(APPLICATION_ALIASES, key=len, reverse=True)
    calls = []
    remaining = remainder.lower()
    while remaining:
        alias = next((name for name in aliases if remaining == name or remaining.startswith(name + " ") or remaining.startswith(name + ",")), None)
        if alias is None:
            if not calls:
                # A garbled first name must not hide later explicit app names
                # by falling back to a model that can omit or replace it.
                known_later = any(
                    re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", remaining)
                    for name in aliases
                )
                if known_later:
                    raise PlanClarification(
                        "I could not understand the complete application list: "
                        f"'{remainder}'. Please repeat the application names clearly. "
                        "No actions were started."
                    )
                # Preserve dynamic discovery for applications outside this
                # bounded alias set; the general planner handles the request.
                return None
            raise PlanClarification(
                "I could not resolve every application in that request. "
                f"Please clarify this part: '{remaining}'. No actions were started."
            )
        calls.append(_call("open_application", app_name=APPLICATION_ALIASES[alias]))
        remaining = remaining[len(alias):].lstrip()
        if remaining.startswith(","):
            remaining = remaining[1:].lstrip()
            if not remaining:
                raise PlanClarification("Which application should follow the comma?")
        if remaining.startswith("and "):
            remaining = remaining[4:].lstrip()
        if remaining == "and":
            raise PlanClarification("Which application should follow 'and'?")
    if search_call:
        calls.append(search_call)
    return calls or None
