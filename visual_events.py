from __future__ import annotations

import json
import time
import uuid
from typing import Final, Literal

from nats.aio.client import Client as NATS


# =========================================================
# ULTRON VISUAL EVENT BUS
# Central semantic event publisher for the ULTRON entity.
# =========================================================

VISUAL_SUBJECT: Final[str] = "ultron.visual"


UltronVisualMode = Literal[
    "offline",
    "starting",
    "idle",
    "listening",
    "thinking",
    "executing",
    "alert",
    "focus",
    "sleep",
]


VALID_MODES: Final[frozenset[str]] = frozenset(
    {
        "offline",
        "starting",
        "idle",
        "listening",
        "thinking",
        "executing",
        "alert",
        "focus",
        "sleep",
    }
)


async def publish_visual_event(
    nc: NATS,
    mode: UltronVisualMode,
    *,
    source: str,
    task_id: str | None = None,
) -> None:
    """
    Publish one validated semantic ULTRON visual event.

    The caller owns the NATS connection.

    This function:
    - validates the requested visual mode
    - validates the event source
    - creates a unique event ID
    - timestamps the event
    - publishes to the shared ULTRON visual subject
    - flushes the connection so the event is delivered promptly
    """

    if not nc.is_connected:
        raise RuntimeError(
            "Cannot publish visual event: NATS connection is offline."
        )

    if mode not in VALID_MODES:
        raise ValueError(
            f"Unsupported ULTRON visual mode: {mode!r}"
        )

    normalized_source = source.strip()

    if not normalized_source:
        raise ValueError(
            "Visual event source cannot be empty."
        )

    payload: dict[str, str | int] = {
        "event": mode,
        "source": normalized_source,
        "timestamp": int(time.time() * 1000),
        "eventId": str(uuid.uuid4()),
    }

    if task_id is not None:
        normalized_task_id = task_id.strip()

        if normalized_task_id:
            payload["taskId"] = normalized_task_id

    await nc.publish(
        VISUAL_SUBJECT,
        json.dumps(
            payload,
            separators=(",", ":"),
        ).encode("utf-8"),
    )

    await nc.flush()