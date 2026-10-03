"""Deterministic intent normalization and safety guards for ULTRON.

This layer sits between LLM tool selection and physical execution. It does not
perform any operating-system actions. Its job is to normalize ambiguous tool
calls, preserve user intent across common LLM decompositions, reject incomplete
requests, and provide a bounded replay plan for safe repeated tasks.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any


# Browser application names are applications, not web destinations.
BROWSER_APP_ALIASES = frozenset(
    {
        "chrome",
        "google chrome",
        "chrome browser",
        "edge",
        "microsoft edge",
        "edge browser",
        "opera",
        "opera gx",
        "firefox",
        "mozilla firefox",
        "brave",
        "brave browser",
        "vivaldi",
    }
)

# Site names for which we can construct a deterministic search URL without
# needing browser DOM automation.
SITE_SEARCH_TEMPLATES: dict[str, str] = {
    "youtube": "https://www.youtube.com/results?search_query={query}",
    "google": "https://www.google.com/search?q={query}",
    "github": "https://github.com/search?q={query}",
    "reddit": "https://www.reddit.com/search/?q={query}",
    "bing": "https://www.bing.com/search?q={query}",
    "duckduckgo": "https://duckduckgo.com/?q={query}",
}

SITE_ALIASES = frozenset(SITE_SEARCH_TEMPLATES) | frozenset(
    {
        "netflix",
        "hotstar",
        "disney hotstar",
        "google docs",
        "docs",
        "google drive",
        "chatgpt",
    }
)

# Only these operations are silently replayable. Destructive, state-mutating,
# arbitrary-code, power, clipboard-write, and process-kill actions must require
# an explicit fresh request.
REPLAYABLE_TOOLS = frozenset(
    {
        "open_application",
        "open_website",
        "live_web_search",
        "query_knowledge_base",
        "get_system_telemetry",
    }
)

MAX_TOOL_CALLS_PER_TASK = 32


class IntentNormalizationError(ValueError):
    """Raised when an LLM plan cannot be made safe/deterministic."""


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "function": {
            "name": name,
            "arguments": arguments,
        }
    }


def _extract_call(tool: Any) -> tuple[str | None, dict[str, Any]]:
    if isinstance(tool, dict):
        function = tool.get("function") or {}
        name = function.get("name")
        args = function.get("arguments", {})
    else:
        function = getattr(tool, "function", None)
        name = getattr(function, "name", None)
        args = getattr(function, "arguments", {})

    if isinstance(args, str):
        try:
            import json

            parsed = json.loads(args)
            args = parsed if isinstance(parsed, dict) else {}
        except Exception:
            args = {}

    return name, dict(args or {})


def is_replay_request(prompt: str) -> bool:
    """Return True when the user explicitly requests a previous task again."""

    text = _normalize_text(prompt)
    replay_patterns = (
        r"\bdo (?:the )?(?:above|previous|last|same) task\b",
        r"\brepeat (?:the )?(?:above|previous|last|same)(?: task)?\b",
        r"\bredo (?:the )?(?:above|previous|last|same)(?: task)?\b",
        r"\bdo that again\b",
        r"\brepeat that\b",
        r"\brun that again\b",
        r"\bperform that again\b",
        r"\bsame thing again\b",
        r"\bdo the same thing\b",
    )
    return any(re.search(pattern, text) for pattern in replay_patterns)


def extract_replay_plan(prompt: str, previous_plan: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Return a safe previous plan when the user explicitly requests replay."""

    if not previous_plan:
        return None

    text = _normalize_text(prompt)

    replay_patterns = (
        r"\bdo (?:the )?(?:above|previous|last|same) task\b",
        r"\brepeat (?:the )?(?:above|previous|last|same)(?: task)?\b",
        r"\bredo (?:the )?(?:above|previous|last|same)(?: task)?\b",
        r"\bdo that again\b",
        r"\brepeat that\b",
        r"\brun that again\b",
        r"\bperform that again\b",
        r"\bsame thing again\b",
        r"\bdo the same thing\b",
    )

    if any(re.search(pattern, text) for pattern in replay_patterns):
        return deepcopy(previous_plan)

    return None


def looks_incomplete_request(prompt: str) -> bool:
    """Detect high-confidence unfinished voice/STT requests.

    This deliberately avoids treating every trailing ellipsis as incomplete.
    It focuses on clauses that grammatically require another argument.
    """

    text = str(prompt or "").strip()

    if not text:
        return True

    patterns = (
        r"\bapp(?:lication)?\s+(?:named|called)\s*(?:\.\.\.|…)?$",
        r"\b(?:file|folder|program|site|website)\s+(?:named|called)\s*(?:\.\.\.|…)?$",
        r"\b(?:search|look|look up)\s+(?:for\s*)?(?:\.\.\.|…)?$",
        r"\b(?:and|then|with|for|named|called)\s+(?:\.\.\.|…)?$",
    )

    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def infer_site_from_prompt(prompt: str) -> str | None:
    """Infer a known website from phrases such as 'search X on YouTube'."""

    text = _normalize_text(prompt)

    for site in sorted(SITE_ALIASES, key=len, reverse=True):
        escaped = re.escape(site)
        if re.search(rf"\b(?:on|in|inside|within|through)\s+{escaped}\b", text):
            return site

    # 'open YouTube and search ...' / 'YouTube, then search ...'
    for site in sorted(SITE_ALIASES, key=len, reverse=True):
        escaped = re.escape(site)
        if re.search(rf"\b(?:open|visit|go to|navigate to)\s+{escaped}\b", text):
            return site

    return None


def infer_query_from_prompt(prompt: str, site: str | None) -> str | None:
    """Infer a web query when a model emits an incomplete website call."""

    if not site:
        return None

    text = str(prompt or "").strip()

    patterns = (
        rf"\bsearch(?:\s+for)?\s+(.+?)\s+(?:on|in|inside|within|through)\s+{re.escape(site)}(?:[.!?]|$)",
        rf"\bsearch\s+(.+?)\s+(?:on|in|inside|within|through)\s+(?:it|the site)(?:[.!?]|$)",
    )

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            query = match.group(1).strip(" \t\r\n,.;:!?\"'")
            if query:
                return query

    return None


def build_site_search_url(site: str, query: str) -> str | None:
    normalized_site = _normalize_text(site)
    template = SITE_SEARCH_TEMPLATES.get(normalized_site)
    if not template:
        return None

    from urllib.parse import quote_plus

    return template.format(query=quote_plus(str(query).strip()))


def _normalize_open_website_args(
    *,
    prompt: str,
    args: dict[str, Any],
    last_web_target: str | None,
) -> tuple[str, dict[str, Any] | None]:
    raw_target = str(args.get("target", "") or "").strip()
    raw_query = str(args.get("query", "") or "").strip()

    # Browser names belong to open_application, not open_website. Do not
    # silently discard a paired query because this would create a false sense
    # that the browser-specific search occurred.
    if _normalize_text(raw_target) in BROWSER_APP_ALIASES:
        if raw_query:
            raise IntentNormalizationError(
                "The request targets a specific browser and a search query, "
                "but browser-specific navigation is not available yet."
            )
        application_args = {"app_name": raw_target}
        return "open_application", application_args

    if not raw_target:
        inferred_site = last_web_target or infer_site_from_prompt(prompt)
        if inferred_site and raw_query:
            return "open_website", {
                "target": inferred_site,
                "query": raw_query,
                "count": args.get("count", 1),
            }

        inferred_query = infer_query_from_prompt(prompt, inferred_site)
        if inferred_site and inferred_query:
            return "open_website", {
                "target": inferred_site,
                "query": inferred_query,
                "count": args.get("count", 1),
            }

        raise IntentNormalizationError(
            "A website search query was provided without a website target."
        )

    target_normalized = _normalize_text(raw_target)

    # A site-specific query becomes one atomic navigation action.
    if raw_query and target_normalized in SITE_SEARCH_TEMPLATES:
        return "open_website", {
            "target": target_normalized,
            "query": raw_query,
            "count": args.get("count", 1),
        }

    return "open_website", {
        "target": raw_target,
        "count": args.get("count", 1),
        **({"query": raw_query} if raw_query else {}),
    }


def normalize_tool_calls(
    prompt: str,
    raw_tool_calls: list[Any],
) -> tuple[list[dict[str, Any]], str | None]:
    """Normalize and validate an LLM tool-call batch.

    Returns:
        (normalized_calls, clarification_message)
    """

    if len(raw_tool_calls) > MAX_TOOL_CALLS_PER_TASK:
        return [], (
            "That request produced too many actions at once. "
            f"I can safely process up to {MAX_TOOL_CALLS_PER_TASK} actions in one task."
        )

    extracted: list[tuple[str, dict[str, Any]]] = []
    for tool in raw_tool_calls:
        name, args = _extract_call(tool)
        if not name:
            continue
        extracted.append((str(name), args))

    normalized: list[dict[str, Any]] = []
    last_web_target: str | None = None

    # Track explicit website targets so a later query-only call can be merged.
    for name, args in extracted:
        if name == "open_website":
            raw_target = str(args.get("target", "") or "").strip()
            if raw_target:
                browser_check = _normalize_text(raw_target)
                known_site_or_domain = (
                    browser_check in SITE_ALIASES
                    or browser_check in BROWSER_APP_ALIASES
                    or "://" in browser_check
                    or "." in browser_check
                )
                if (
                    last_web_target
                    and not known_site_or_domain
                    and not str(args.get("query", "") or "").strip()
                    and re.search(r"\bsearch\b", _normalize_text(prompt))
                ):
                    # Repair a common model decomposition where the second
                    # website call places the search phrase in `target`.
                    args = dict(args)
                    args["query"] = raw_target
                    args["target"] = ""
                elif browser_check not in BROWSER_APP_ALIASES:
                    last_web_target = browser_check

        if name == "open_website":
            try:
                normalized_name, normalized_args = _normalize_open_website_args(
                    prompt=prompt,
                    args=args,
                    last_web_target=last_web_target,
                )
            except IntentNormalizationError as exc:
                return [], (
                    "I need one more detail before I execute that: "
                    f"{exc}"
                )

            if normalized_name == "open_application":
                normalized.append(_tool_call(normalized_name, normalized_args or {}))
                continue

            # Merge query-only calls into the immediately preceding website action
            # when they refer to the same site. This fixes the common Qwen
            # decomposition: open_website(target=YouTube), then
            # open_website(query=quantum computers).
            if (
                normalized_args
                and normalized_args.get("query")
                and not str(args.get("target", "") or "").strip()
                and normalized
            ):
                for previous in reversed(normalized):
                    previous_name, previous_args = _extract_call(previous)
                    if previous_name == "open_website" and previous_args.get("target"):
                        previous_args["query"] = normalized_args["query"]
                        previous["function"]["arguments"] = previous_args
                        break
                else:
                    normalized.append(
                        _tool_call("open_website", normalized_args)
                    )
            else:
                normalized.append(
                    _tool_call(
                        "open_website",
                        normalized_args or {},
                    )
                )
            continue

        # Normalize browser aliases in open_application.
        if name == "open_application":
            app_name = str(args.get("app_name", "") or "").strip()
            if not app_name:
                return [], "Which application should I open?"
            normalized.append(
                _tool_call(
                    "open_application",
                    {"app_name": app_name},
                )
            )
            continue

        # Required-argument guards for the remaining high-impact tools.
        required = {
            "run_python_script": "script_path",
            "recall_facts": "search_term",
            "query_knowledge_base": "query",
            "live_web_search": "query",
            "control_media": "action",
            "terminate_process": "process_name",
            "system_power_control": "command",
            "organize_folder": "target_folder",
            "activate_protocol": "protocol",
            "manage_clipboard": "action",
        }

        if name in required:
            key = required[name]
            if not str(args.get(key, "") or "").strip():
                return [], f"I need the '{key}' value before I execute that."

        normalized.append(_tool_call(name, args))

    # Suppress a knowledge-base lookup when it is merely a duplicate of an
    # explicit on-site search request.
    website_queries = {
        _extract_call(call)[1].get("query", "").strip().lower()
        for call in normalized
        if _extract_call(call)[0] == "open_website"
        and _extract_call(call)[1].get("query")
    }

    filtered: list[dict[str, Any]] = []
    for call in normalized:
        name, args = _extract_call(call)
        normalized_query = str(args.get("query", "")).strip().lower()

        if (
            name == "query_knowledge_base"
            and normalized_query in website_queries
        ):
            continue

        if (
            name == "live_web_search"
            and normalized_query in website_queries
        ):
            continue

        filtered.append(call)

    estimated_actions = 0
    for call in filtered:
        name, args = _extract_call(call)
        if name == "open_application":
            estimated_actions += 1
        elif name == "open_website":
            try:
                estimated_actions += max(1, min(int(args.get("count", 1)), 15))
            except (TypeError, ValueError):
                estimated_actions += 1

    if estimated_actions > MAX_TOOL_CALLS_PER_TASK:
        return [], (
            "That request contains too many physical actions for one safe task "
            f"(maximum {MAX_TOOL_CALLS_PER_TASK})."
        )

    # Dedupe exact non-repeatable action requests. Explicit website `count`
    # remains the preferred mechanism for intentional repetition.
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()

    for call in filtered:
        name, args = _extract_call(call)
        if name in {"open_application", "open_website"}:
            key = (
                name
                + ":"
                + repr(sorted((str(k), repr(v)) for k, v in args.items()))
            )
            if key in seen:
                continue
            seen.add(key)
        deduped.append(call)

    return deduped, None


def build_replay_plan(normalized_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Persist only safe, deterministic operations for future replay."""

    plan: list[dict[str, Any]] = []

    for call in normalized_calls:
        name, args = _extract_call(call)
        if name not in REPLAYABLE_TOOLS:
            continue
        plan.append(
            _tool_call(
                name,
                deepcopy(args),
            )
        )

    return plan
