"""Bounded microphone delivery and sample-based utterance segmentation."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, replace
from threading import Lock
from typing import Any


class TranscriptionWorker:
    """One inference in flight and one complete utterance waiting.

    The audio consumer never waits for inference. Overload invalidates both
    pending and in-flight results rather than executing an old command later.
    Native inference cannot be interrupted, but its invalidated result is ignored.
    All methods except the supplied inference callable run on the asyncio loop.
    """
    def __init__(self, transcribe, on_result, on_discard, *, executor=None,
                 max_age_seconds=15.0, clock=time.monotonic):
        if max_age_seconds <= 0:
            raise ValueError('Transcription age limit must be positive')
        self.transcribe = transcribe
        self.on_result = on_result
        self.on_discard = on_discard
        self.executor = executor
        self.max_age_seconds = max_age_seconds
        self.clock = clock
        self.queue = asyncio.Queue(maxsize=1)
        self.generation = 0
        self.busy = False

    def submit(self, audio, captured_at):
        if self.queue.full():
            self.generation += 1
            self.queue.get_nowait()
            return False
        self.queue.put_nowait((audio, captured_at, self.generation))
        return True

    async def run(self):
        loop = asyncio.get_running_loop()
        while True:
            audio, captured_at, generation = await self.queue.get()
            if self.clock() - captured_at > self.max_age_seconds:
                await self.on_discard('utterance expired before transcription')
                continue
            self.busy = True
            started = self.clock()
            try:
                result = await loop.run_in_executor(self.executor, self.transcribe, audio)
                if generation != self.generation:
                    # submit() already reported this overload episode.
                    continue
                if self.clock() - captured_at > self.max_age_seconds:
                    await self.on_discard('utterance expired during transcription')
                    continue
                await self.on_result(result, self.clock() - started)
            finally:
                self.busy = False


@dataclass(frozen=True)
class AudioFrame:
    samples: Any
    captured_at: float
    sequence: int
    muted: bool = False
    discontinuity: bool = False
    discontinuity_reason: str | None = None


class AudioMailbox:
    """One bounded buffer and at most one pending loop notification.

    push() runs on the capture thread; get() runs on the asyncio loop.
    Overflow drops the backlog and marks the next frame as discontinuous.
    """
    def __init__(self, loop, capacity: int):
        if capacity < 1:
            raise ValueError("Audio mailbox capacity must be positive")
        self.loop = loop
        self.capacity = capacity
        self.dropped_frames = 0
        self._frames = deque()
        self._lock = Lock()
        self._ready = asyncio.Event()
        self._notified = False
        self._closed = False

    def push(self, frame: AudioFrame) -> None:
        with self._lock:
            if self._closed:
                return
            if len(self._frames) >= self.capacity:
                self.dropped_frames += len(self._frames)
                self._frames.clear()
                frame = replace(frame, discontinuity=True, discontinuity_reason="application mailbox overflow")
            self._frames.append(frame)
            notify = not self._notified
            self._notified = True
        if notify:
            try:
                self.loop.call_soon_threadsafe(self._ready.set)
            except RuntimeError:
                # A late PortAudio callback may race loop shutdown.
                self.close()

    async def get(self) -> AudioFrame:
        while True:
            with self._lock:
                if self._frames:
                    return self._frames.popleft()
                if self._closed:
                    raise RuntimeError("Audio mailbox closed")
                self._ready.clear()
                self._notified = False
            await self._ready.wait()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._frames.clear()
        try:
            self.loop.call_soon_threadsafe(self._ready.set)
        except RuntimeError:
            pass


@dataclass(frozen=True)
class SegmentResult:
    started: bool = False
    blocks: tuple | None = None
    discarded_reason: str | None = None


class UtteranceSegmenter:
    """Reject damaged/overlong utterances until a complete quiet interval.

    All audio durations count samples rather than consumer wall time.
    No partial recording is returned on overflow or at the duration limit.
    """
    def __init__(self, *, sample_rate: int, silence_seconds: float,
                 max_seconds: float, preroll_blocks: int, max_backlog_seconds: float):
        if sample_rate <= 0 or silence_seconds <= 0 or max_seconds <= 0 or preroll_blocks < 0 or max_backlog_seconds <= 0:
            raise ValueError("Invalid audio segmentation configuration")
        self.silence_samples = round(sample_rate * silence_seconds)
        self.max_samples = round(sample_rate * max_seconds)
        self.max_backlog_seconds = max_backlog_seconds
        self.preroll = deque(maxlen=preroll_blocks)
        self.blocks = []
        self.sample_count = 0
        self.quiet_samples = 0
        self.recording = False
        self.discarding = False
        self.last_sequence = None

    def _clear_recording(self):
        self.blocks.clear()
        self.preroll.clear()
        self.sample_count = 0
        self.quiet_samples = 0
        self.recording = False

    def _reject(self, reason: str) -> SegmentResult:
        notify = not self.discarding
        self._clear_recording()
        self.discarding = True
        return SegmentResult(discarded_reason=reason if notify else None)

    def feed(self, frame: AudioFrame, *, speech: bool, now: float,
             muted: bool = False) -> SegmentResult:
        gap = self.last_sequence is not None and frame.sequence != self.last_sequence + 1
        self.last_sequence = frame.sequence
        if frame.muted or muted:
            # Keep discarding if TTS cut an utterance in half; otherwise the
            # first clean post-TTS request can start without an extra delay.
            self.discarding = self.discarding or self.recording
            self._clear_recording()
            return SegmentResult()
        if now - frame.captured_at > self.max_backlog_seconds:
            return self._reject("audio backlog exceeded the latency limit")
        if frame.discontinuity or gap:
            reason = frame.discontinuity_reason or ("capture status flag" if frame.discontinuity else "frame sequence gap")
            return self._reject(f"microphone audio was lost ({reason})")
        count = len(frame.samples)
        if self.discarding:
            self.quiet_samples = 0 if speech else self.quiet_samples + count
            if self.quiet_samples >= self.silence_samples:
                self.discarding = False
                self.quiet_samples = 0
            return SegmentResult()
        started = False
        if not self.recording:
            if not speech:
                self.preroll.append(frame.samples)
                return SegmentResult()
            self.recording = True
            started = True
            self.blocks = list(self.preroll)
            self.preroll.clear()
            self.sample_count = sum(len(block) for block in self.blocks)
        if self.sample_count + count > self.max_samples:
            return self._reject("utterance exceeded the recording duration limit")
        self.blocks.append(frame.samples)
        self.sample_count += count
        self.quiet_samples = 0 if speech else self.quiet_samples + count
        if self.quiet_samples >= self.silence_samples:
            blocks = tuple(self.blocks)
            self._clear_recording()
            return SegmentResult(blocks=blocks)
        return SegmentResult(started=started)
