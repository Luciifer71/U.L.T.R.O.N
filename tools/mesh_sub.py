import asyncio
import json
from nats.aio.client import Client as NATS

async def message_handler(msg):
    payload = json.loads(msg.data.decode())
    print(f"[ULTRON NETWORK EVENT RECEIVED]: {payload}")

async def main():
    nc = NATS()
    await nc.connect(servers=["nats://localhost:4222"])

    await nc.subscribe("ultron.>", cb=message_handler)
    print("Subscribed to 'ultron.events'. Waiting for messages...")

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        await nc.drain()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down subscriber.")