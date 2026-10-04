from __future__ import annotations

import pytest

from ultron_control.intent_guard import (
    build_replay_plan,
    extract_replay_plan,
    infer_query_from_prompt,
    looks_incomplete_request,
    normalize_tool_calls,
)


def call(name: str, arguments: dict) -> dict:
    return {"function": {"name": name, "arguments": arguments}}


def test_site_search_is_atomic() -> None:
    normalized, clarification = normalize_tool_calls(
        "Open YouTube and search quantum computers on it.",
        [
            call(
                "open_website",
                {
                    "target": "youtube",
                    "query": "quantum computers",
                },
            )
        ],
    )

    assert clarification is None
    assert len(normalized) == 1
    assert normalized[0]["function"]["arguments"]["target"] == "youtube"
    assert normalized[0]["function"]["arguments"]["query"] == "quantum computers"


def test_query_only_web_call_merges_with_previous_site() -> None:
    normalized, clarification = normalize_tool_calls(
        "Open YouTube and search quantum computers on it.",
        [
            call("open_website", {"target": "youtube"}),
            call("open_website", {"query": "quantum computers"}),
        ],
    )

    assert clarification is None
    assert len(normalized) == 1
    args = normalized[0]["function"]["arguments"]
    assert args["target"] == "youtube"
    assert args["query"] == "quantum computers"


def test_query_in_target_is_repaired() -> None:
    normalized, clarification = normalize_tool_calls(
        "Open YouTube and search quantum computers on it.",
        [
            call("open_website", {"target": "youtube"}),
            call("open_website", {"target": "quantum computers"}),
        ],
    )

    assert clarification is None
    assert len(normalized) == 1
    args = normalized[0]["function"]["arguments"]
    assert args["target"] == "youtube"
    assert args["query"] == "quantum computers"


def test_browser_name_is_application() -> None:
    normalized, clarification = normalize_tool_calls(
        "Open Chrome.",
        [call("open_website", {"target": "chrome"})],
    )

    assert clarification is None
    assert normalized == [
        call("open_application", {"app_name": "chrome"})
    ]


def test_browser_specific_search_requests_clarification() -> None:
    normalized, clarification = normalize_tool_calls(
        "Open Chrome and search quantum computers.",
        [
            call(
                "open_website",
                {
                    "target": "chrome",
                    "query": "quantum computers",
                },
            )
        ],
    )

    assert normalized == []
    assert clarification is not None
    assert "browser" in clarification.lower()


def test_duplicate_knowledge_search_is_removed() -> None:
    normalized, clarification = normalize_tool_calls(
        "Open YouTube and search quantum computers on it.",
        [
            call(
                "open_website",
                {
                    "target": "youtube",
                    "query": "quantum computers",
                },
            ),
            call(
                "query_knowledge_base",
                {
                    "query": "quantum computers",
                },
            ),
            call(
                "live_web_search",
                {
                    "query": "quantum computers",
                },
            ),
        ],
    )

    assert clarification is None
    assert normalized == [
        call(
            "open_website",
            {
                "target": "youtube",
                "query": "quantum computers",
                "count": 1,
            },
        )
    ]


def test_incomplete_named_app_is_blocked() -> None:
    assert looks_incomplete_request(
        "open YouTube and also an app named..."
    )


def test_normal_request_is_not_blocked() -> None:
    assert not looks_incomplete_request(
        "open YouTube and search quantum computers."
    )


def test_replay_plan_only_contains_safe_tools() -> None:
    calls = [
        call("open_application", {"app_name": "notion"}),
        call(
            "open_website",
            {
                "target": "youtube",
                "query": "quantum computers",
                "count": 1,
            },
        ),
        call(
            "terminate_process",
            {
                "process_name": "chrome",
            },
        ),
    ]

    plan = build_replay_plan(calls)
    assert len(plan) == 2
    assert all(
        c["function"]["name"]
        in {"open_application", "open_website"}
        for c in plan
    )


def test_replay_detection_requires_stored_plan() -> None:
    assert extract_replay_plan(
        "do the above task",
        [
            call(
                "open_application",
                {
                    "app_name": "notion",
                },
            )
        ],
    )


def test_site_query_can_be_inferred_from_prompt() -> None:
    query = infer_query_from_prompt(
        "open YouTube and search quantum computers on it.",
        "youtube",
    )
    assert query == "quantum computers"


def test_missing_required_argument_is_rejected() -> None:
    normalized, clarification = normalize_tool_calls(
        "open an app",
        [
            call(
                "open_application",
                {
                    "app_name": "",
                },
            )
        ],
    )

    assert normalized == []
    assert clarification == "Which application should I open?"



def test_conversational_ack_is_not_an_action_request() -> None:
    from ultron_control.intent_guard import is_conversational_only

    assert is_conversational_only("Thank you")
    assert is_conversational_only("Okay, good job")
    assert not is_conversational_only("Okay, open Chrome")


def test_task_status_request_is_detected() -> None:
    from ultron_control.intent_guard import is_task_status_request

    assert is_task_status_request("What's the status on the above task that I gave you?")
    assert is_task_status_request("How is the previous task performing?")
    assert not is_task_status_request("Open Forza Horizon 6.")
