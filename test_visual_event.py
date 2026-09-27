"""
ULTRON Visual Event Test Publisher

Development-only utility used to verify the complete:

Python → NATS → WebSocket → React → Entity Simulation

pipeline.

This file does not belong to ULTRON's production runtime.
"""

from __future__ import annotations

import argparse
import asyncio
import time
import uuid

import nats


NATS_URL = "nats://127.0.0.1:4222"
VISUAL_SUBJECT = "ultron.visual"

VALID_EVENTS = {
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


async def publish_visual_event(event: str) -> None:
    if event not in VALID_EVENTS:
        raise ValueError(
            f"Unsupported event: {event!r}. "
            f"Valid events: {', '.join(sorted(VALID_EVENTS))}"
        )

    nc = await nats.connect(
        servers=[NATS_URL],
        name="ultron-visual-test-publisher",
        connect_timeout=5,
        max_reconnect_attempts=3,
        reconnect_time_wait=2,
    )

    try:
        payload = {
            "event": event,
            "source": "test-publisher",
            "timestamp": int(time.time() * 1000),
            "eventId": str(uuid.uuid4()),
        }

        import json

        await nc.publish(
            VISUAL_SUBJECT,
            json.dumps(payload).encode("utf-8"),
        )

        await nc.flush(timeout=2)

        print(
            f"[ULTRON TEST] Published {event!r} "
            f"→ {VISUAL_SUBJECT}"
        )

    finally:
        await nc.drain()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish a ULTRON visual event."
    )

    parser.add_argument(
        "event",
        choices=sorted(VALID_EVENTS),
        help="Visual state to publish.",
    )

    args = parser.parse_args()

    asyncio.run(
        publish_visual_event(args.event)
    )


if __name__ == "__main__":
    main()