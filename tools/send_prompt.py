import asyncio
import json
import os
from nats.aio.client import Client as NATS

NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")


async def main():
    nc = NATS()
    try:
        await nc.connect(NATS_URL)
    except Exception as e:
        print(f"[NATS ERROR]: Could not connect to NATS server on 4222: {e}")
        return

    print("=" * 50)
    print("      ULTRON TERMINAL INTERFACE READY")
    print(" Type your question and press Enter. (Type 'exit' to quit)")
    print("=" * 50 + "\n")

    try:
        while True:
            prompt = input("You > ").strip()

            if not prompt:
                continue
            if prompt.lower() in ["exit", "quit"]:
                print("Exiting Ultron terminal interface.")
                break

            payload = json.dumps({"prompt": prompt}).encode()
            await nc.publish("ultron.intent", payload)
            await nc.flush()
            print("[DISPATCHED TO ULTRON BRAIN]\n")

    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    except Exception as e:
        print(f"[COMMUNICATION ERROR]: {e}")
    finally:
        # Suppress socket errors during shutdown if NATS closes abruptly
        try:
            await nc.drain()
            await nc.close()
        except Exception:
            pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[ULTRON CLI]: Closed gracefully.")