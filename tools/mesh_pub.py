import asyncio
import json
from datetime import datetime, timezone
import nats


async def main():
    nc = await nats.connect("nats://localhost:4222")

    payload = {
        "device_id": "laptop_01",
        "event": "wake_word_detected",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    await nc.publish("ultron.events", json.dumps(payload).encode())
    await nc.flush()
    print(f"Published: {payload}")

    await nc.close()


if __name__ == "__main__":
    asyncio.run(main())