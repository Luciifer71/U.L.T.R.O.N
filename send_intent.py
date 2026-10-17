"""Send one live typed command and wait for its matched brain response."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import uuid

from dotenv import load_dotenv
from nats.aio.client import Client as NATS


async def send_command(prompt: str, timeout: float = 30) -> dict:
    nc = NATS()
    request_id = str(uuid.uuid4())
    response = asyncio.get_running_loop().create_future()

    async def receive(msg):
        try:
            data = json.loads(msg.data.decode())
        except (ValueError, UnicodeError):
            return
        if isinstance(data, dict) and data.get("requestId") == request_id and not response.done():
            response.set_result(data)

    try:
        await nc.connect(os.getenv("NATS_URL", "nats://localhost:4222"), connect_timeout=3)
        await nc.subscribe("ultron.voice", cb=receive)
        await nc.flush()
        await nc.publish("ultron.intent", json.dumps({
            "prompt": prompt, "requestId": request_id,
        }).encode())
        await nc.flush()
        return await asyncio.wait_for(response, timeout)
    finally:
        await nc.close()


def main() -> int:
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
    parser = argparse.ArgumentParser(description=__doc__, epilog="This executes live commands. Start the updated brain first.")
    parser.add_argument("prompt", help="Quoted command to send to Ultron")
    parser.add_argument("--timeout", type=float, default=30, help="Response wait in seconds (default: 30)")
    args = parser.parse_args()
    if not args.prompt.strip() or args.timeout <= 0:
        parser.error("Provide a nonempty prompt and a positive timeout.")
    try:
        result = asyncio.run(send_command(args.prompt, args.timeout))
    except TimeoutError:
        print("No matched response before timeout. The command may still be running; check the brain log before retrying.")
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"Command transport failed: {type(exc).__name__}. Check NATS and the brain logs.")
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if result.get("execution", {}).get("success") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
