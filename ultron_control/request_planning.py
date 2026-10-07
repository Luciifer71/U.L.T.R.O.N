"""Complete plans for a deliberately bounded, explicit launch grammar.

No fuzzy recognition, shell commands, or execution happens here. Requests
outside this grammar remain on the model path; ambiguous target lists inside
the grammar require clarification instead of silently dropping a target.
"""
from __future__ import annotations

import re
import unicodedata


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
    text = unicodedata.normalize('NFC', text).casefold()
    return ' '.join(''.join(char if unicodedata.category(char)[0] in {'L', 'N', 'M'} else ' ' for char in text).split())


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
        if function.get('name') in {'operate_resource', 'run_python_script'}:
            error = validate_resource_target(prompt, function)
            if error:
                return error
            arguments = function.get('arguments', {})
            if arguments.get('operation') in {'open', 'launch'}:
                target = str(arguments.get('target', '')).casefold().strip()
                planned.add(APPLICATION_ALIASES.get(target, target).casefold())
                editor = str(arguments.get('editor') or '').casefold()
                if editor:
                    planned.add(APPLICATION_ALIASES.get(editor, editor).casefold())
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


def validate_resource_target(prompt: str, function: dict) -> str | None:
    """Conservative current-request grounding for typed file operations.

    This deliberately asks for clarification on conditions, negation, or
    questions about execution. It is not a general natural-language proof.
    Catalog matches never substitute for the user's authorization.
    """
    arguments = function.get('arguments', {})
    operation = arguments.get('operation', 'run_script' if function.get('name') == 'run_python_script' else '')
    target = arguments.get('target', arguments.get('script_path', ''))
    allowed = {'open': {'open'}, 'launch': {'open', 'launch', 'start', 'execute'},
               'run_script': {'run', 'execute'}, 'read': {'read'}}
    if operation not in allowed or not isinstance(target, str) or not target.strip():
        return 'Please specify a supported resource operation and target. No actions were started.'
    if re.search(r"\b(?:if|unless|don't|do not|never|why|how)\b", prompt, re.I):
        return 'Please state the resource operation directly, including any conditions. No actions were started.'
    verbs = list(re.finditer(r'\b(open|launch|start|execute|run|read)\s+', prompt, re.I))
    grounded = False
    for index, match in enumerate(verbs):
        if match.group(1).casefold() not in allowed[operation]:
            continue
        prefix = prompt[:match.start()]
        if re.search(r'\b(?:search|find|explain|tell|discuss)\b', prefix, re.I) and not re.search(r'\b(?:and|then|also)\s+(?:(?:then|also)\s+)?$', prefix, re.I):
            continue
        end = verbs[index + 1].start() if index + 1 < len(verbs) else len(prompt)
        if _mentions_target(prompt[match.end():end], target):
            grounded = True
    if not grounded:
        return f"The resource operation or target '{target}' was not explicitly requested. No actions were started."
    root = arguments.get('root')
    if root:
        drive = re.fullmatch(r'([a-z]):[\\/]?', str(root), re.I)
        if not _mentions_target(prompt, str(root)) and not (drive and re.search(r'\b' + drive.group(1) + r'\s+drive\b', prompt, re.I)):
            return 'The proposed folder or drive scope was not named in your request. No actions were started.'
    editor = arguments.get('editor')
    if editor and (operation != 'open' or not _mentions_target(prompt, str(editor))):
        return 'The proposed editor was not requested. No actions were started.'
    extra = arguments.get('arguments', arguments.get('args', []))
    if extra and (not isinstance(extra, list) or any(not isinstance(value, str) or value not in prompt for value in extra)):
        return 'Script and application arguments must be explicitly supplied as literal values. No actions were started.'
    return None


class PlanClarification(ValueError):
    """An explicit launch list could not be parsed completely."""


def explicit_resource_plan(prompt: str) -> list[dict] | None:
    """Single literal resource requests; resolution stays in the catalog."""
    text = prompt.strip().rstrip('.!?')
    match = re.fullmatch(r'(?:please\s+)?(?:(?:can|could|would) you\s+)?(run|execute|read|open)\s+(.+)', text, re.I)
    if not match:
        return None
    verb, target = match.groups()
    if re.search(r'\band not pad\b', target, re.I):
        raise PlanClarification('Did you mean to open the document in Notepad? Please repeat the complete request. No actions were started.')
    if re.search(r"\b(?:and|then|if|unless|with|without|don't|do not|never)\b", target, re.I):
        return None
    target = re.sub(r'\s+(?:for me|please)$', '', target, flags=re.I)
    editor = re.search(r'\s+in\s+(notepad|textedit)$', target, re.I)
    if verb.casefold() == 'open' and not editor:
        return None
    options = {}
    if editor:
        if verb.casefold() != 'open':
            return None
        options['editor'] = editor.group(1)
        target = target[:editor.start()].strip()
    operation = {'run': 'run_script', 'execute': 'run_script', 'read': 'read', 'open': 'open'}[verb.casefold()]
    # Native executable requests remain with the native application planner.
    if operation == 'run_script' and re.search(r'\.(exe|app)$|\bgame$', target, re.I):
        return None
    if operation == 'run_script' and not re.search(r'\.(py|ps1|sh)$|\bscript$', target, re.I):
        return None
    if not target:
        raise PlanClarification('Which resource should I use?')
    return [_call('operate_resource', operation=operation, target=target.strip('"'), **options)]


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
    # File/editor requests belong to the resource planner, not the application
    # alias list. A named editor is not another application launch target.
    if re.search(r'[\\/]|\.(?:txt|md|pdf|docx?|xlsx?|exe|app|py|ps1|sh)\b|\bin (?:notepad|textedit)\b', remainder, re.I):
        return None
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
