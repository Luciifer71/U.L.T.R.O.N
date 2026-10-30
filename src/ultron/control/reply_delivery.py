"""Bounded speech delivery and a separate read-only request lane."""
import asyncio
from collections import deque
import json
import time

from ultron.control.read_requests import read_request_kinds, read_request_reply


class SpeechQueue:
    def __init__(self, speak, *, clock=time.monotonic, limit=16):
        self.speak = speak
        self.clock = clock
        self.limit = limit
        self.pending = deque()
        self.ready = asyncio.Event()
        self.active = None
        self.active_key = None
        self.recent = {}

    def submit(self, text, key=None, ttl=None):
        if not text:
            return False
        now = self.clock()
        self.recent = {k: v for k, v in self.recent.items() if now - v < 10}
        if key:
            if key == self.active_key or key in self.recent:
                return False
            self.pending = deque(item for item in self.pending if item[1] != key)
        if len(self.pending) >= self.limit:
            self.pending.popleft()  # Speech only; never physical actions.
        self.pending.append((text, key, now + ttl if ttl else None))
        self.ready.set()
        return True

    async def cancel(self):
        self.pending.clear()
        self.ready.clear()
        if self.active:
            self.active.cancel()
            try:
                await self.active
            except asyncio.CancelledError:
                pass

    async def run(self):
        try:
            while True:
                await self.ready.wait()
                while self.pending:
                    text, key, deadline = self.pending.popleft()
                    if deadline is not None and self.clock() > deadline:
                        continue
                    self.active_key = key
                    self.active = asyncio.create_task(self.speak(text))
                    try:
                        await self.active
                    except asyncio.CancelledError:
                        if asyncio.current_task().cancelling():
                            raise
                    finally:
                        if key:
                            self.recent[key] = self.clock()
                        self.active = None
                        self.active_key = None
                self.ready.clear()
        finally:
            await self.cancel()


class IntentInbox:
    """NATS callbacks return promptly; mutating actions remain sequential."""
    def __init__(self, brain, nc, handle, classify, limit=16):
        self.brain, self.nc, self.handle, self.classify = brain, nc, handle, classify
        self.pending = asyncio.Queue(maxsize=limit)

    async def receive(self, msg):
        started = time.perf_counter()
        try:
            data = json.loads(msg.data.decode())
            if not isinstance(data, dict):
                return
            prompt = str(data.get('prompt', '')).strip()
            if not prompt:
                return
        except (ValueError, UnicodeError):
            return
        stop = prompt.lower().strip(' .!?') in {'stop speaking', 'cancel speech', 'be quiet'}
        reads = read_request_kinds(prompt) if not stop else None
        kind = '+'.join(reads) if reads else self.classify(prompt)
        if stop or kind:
            if stop:
                await self.nc.publish('ultron.voice.cancel', b'{}')
                reply = 'Speech cancelled. Running actions were not cancelled.'
            elif reads:
                reply = await asyncio.to_thread(read_request_reply, reads, self.brain.google_updates)
            else:
                reply = self.brain.google_updates.spoken_reply(kind)
            speech = reply
            if reads == ('capabilities',):
                speech = ('I can open apps and files, search the web, and report system stats. '
                          'With Google connected, I can read email and calendar updates. '
                          'The full capability list is in the terminal.')
            payload = {'text': reply, 'speech': '' if stop else speech,
                       'silent': stop, 'requestId': data.get('requestId'),
                       'statusKey': 'google-' + kind if kind else None,
                       'speechTtl': 20, 'execution': {'success': True, 'error': None}}
            await self.nc.publish('ultron.voice', json.dumps(payload).encode())
            print(f'[FAST REPLY] kind={kind or "speech-control"} handler_seconds={time.perf_counter() - started:.3f} ' + reply, flush=True)
            return
        try:
            self.pending.put_nowait(msg)
        except asyncio.QueueFull:
            await self.nc.publish('ultron.voice', json.dumps({
                'text': 'The command queue is full. Please wait before trying again.',
                'requestId': data.get('requestId'), 'statusKey': 'queue-full',
                'execution': {'success': False, 'error': 'queue_full'}}).encode())

    async def run(self):
        while True:
            msg = await self.pending.get()
            try:
                await self.handle(msg)
            finally:
                self.pending.task_done()
