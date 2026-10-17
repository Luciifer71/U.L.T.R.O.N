import asyncio
from types import SimpleNamespace

import pytest

from audio_pipeline import AudioFrame, AudioMailbox, UtteranceSegmenter, TranscriptionWorker


def segmenter(**kwargs):
    return UtteranceSegmenter(sample_rate=10, silence_seconds=1.4,
                             max_seconds=kwargs.get("max_seconds", 10),
                             preroll_blocks=2, max_backlog_seconds=2)


def feed(engine, sequence, count=2, speech=True, **kwargs):
    frame = AudioFrame([sequence] * count, captured_at=kwargs.pop("captured_at", 100),
                       sequence=sequence, muted=kwargs.pop("captured_muted", False),
                       discontinuity=kwargs.pop("discontinuity", False))
    return engine.feed(frame, speech=speech, now=kwargs.pop("now", 100), **kwargs)


def test_short_pause_preserves_a_single_utterance_with_preroll():
    engine = segmenter()
    feed(engine, 1, speech=False)
    feed(engine, 2, speech=False)
    assert feed(engine, 3).started
    assert feed(engine, 4, count=8, speech=False).blocks is None
    assert feed(engine, 5).blocks is None
    ready = feed(engine, 6, count=14, speech=False)
    assert [block[0] for block in ready.blocks] == [1, 2, 3, 4, 5, 6]
    assert not engine.recording


def test_endpointing_counts_samples_when_consumer_time_does_not_advance():
    engine = segmenter()
    feed(engine, 1)
    assert feed(engine, 2, count=7, speech=False).blocks is None
    assert feed(engine, 3, count=7, speech=False).blocks is not None


def test_continuous_speech_limit_rejects_entire_recording():
    engine = segmenter(max_seconds=1)
    for sequence in range(1, 6):
        assert feed(engine, sequence).blocks is None
    rejected = feed(engine, 6)
    assert "duration" in rejected.discarded_reason
    assert not engine.blocks
    assert engine.discarding
    for sequence in range(7, 30):
        assert feed(engine, sequence).blocks is None
    feed(engine, 30, count=14, speech=False)
    assert feed(engine, 31).started


def test_sequence_gap_never_returns_command_tail():
    engine = segmenter()
    feed(engine, 1)
    assert "lost" in feed(engine, 3).discarded_reason
    assert feed(engine, 4).blocks is None
    assert feed(engine, 5, count=14, speech=False).blocks is None
    assert feed(engine, 6).started
    ready = feed(engine, 7, count=14, speech=False)
    assert [block[0] for block in ready.blocks] == [6, 7]


def test_native_input_overflow_invalidates_even_first_frame():
    engine = segmenter()
    assert feed(engine, 1, discontinuity=True).discarded_reason
    assert feed(engine, 2).blocks is None


def test_old_audio_is_rejected_then_recovers_after_fresh_quiet():
    engine = segmenter()
    assert "backlog" in feed(engine, 1, captured_at=97).discarded_reason
    assert feed(engine, 2).blocks is None
    feed(engine, 3, count=14, speech=False)
    assert feed(engine, 4).started


def test_repeated_faults_produce_one_notice_per_discard_episode():
    engine = segmenter()
    assert feed(engine, 1, discontinuity=True).discarded_reason
    assert feed(engine, 2, discontinuity=True).discarded_reason is None


def test_capture_time_tts_gate_survives_delayed_consumption():
    engine = segmenter()
    assert not feed(engine, 1, captured_muted=True, muted=False).started
    assert not engine.blocks
    assert feed(engine, 2).started


def test_tts_cut_during_speech_rejects_remaining_tail():
    engine = segmenter()
    feed(engine, 1)
    feed(engine, 2, captured_muted=True)
    assert feed(engine, 3).blocks is None
    assert engine.discarding
    feed(engine, 4, count=14, speech=False)
    assert feed(engine, 5).started


def test_mailbox_bounds_audio_and_pending_notifications():
    notifications = []
    mailbox = AudioMailbox(SimpleNamespace(call_soon_threadsafe=lambda callback: notifications.append(callback)), capacity=3)
    for sequence in range(100):
        mailbox.push(AudioFrame([sequence], 0, sequence))
    assert len(notifications) == 1
    assert mailbox.dropped_frames == 99
    frame = asyncio.run(mailbox.get())
    assert frame.sequence == 99
    assert frame.discontinuity


def test_mailbox_thread_delivery_and_close_wakes_waiter():
    async def run():
        mailbox = AudioMailbox(asyncio.get_running_loop(), capacity=2)
        await asyncio.to_thread(mailbox.push, AudioFrame([1], 0, 1))
        assert (await asyncio.wait_for(mailbox.get(), 1)).sequence == 1
        waiter = asyncio.create_task(mailbox.get())
        await asyncio.sleep(0)
        mailbox.close()
        with pytest.raises(RuntimeError, match="closed"):
            await asyncio.wait_for(waiter, 1)
        mailbox.push(AudioFrame([2], 0, 2))
    asyncio.run(run())


def test_mailbox_waiter_receives_new_frame_without_lost_wakeup():
    async def run():
        mailbox = AudioMailbox(asyncio.get_running_loop(), capacity=2)
        for sequence in range(20):
            waiter = asyncio.create_task(mailbox.get())
            await asyncio.sleep(0)
            await asyncio.to_thread(mailbox.push, AudioFrame([sequence], 0, sequence))
            assert (await asyncio.wait_for(waiter, 1)).sequence == sequence
        mailbox.close()
    asyncio.run(run())


def test_transcription_overload_invalidates_inflight_and_pending_results():
    from threading import Event
    from concurrent.futures import ThreadPoolExecutor
    async def run():
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        release = Event()
        delivered = asyncio.Event()
        results = []
        decoded = []
        def infer(audio):
            decoded.append(audio)
            if audio == 'first':
                loop.call_soon_threadsafe(started.set)
                assert release.wait(2)
            return audio
        async def result(text, elapsed):
            results.append(text)
            delivered.set()
        async def discard(reason):
            pytest.fail(reason)
        with ThreadPoolExecutor(max_workers=1) as executor:
            worker = TranscriptionWorker(infer, result, discard, executor=executor)
            worker.submit('first', worker.clock())
            task = asyncio.create_task(worker.run())
            try:
                await asyncio.wait_for(started.wait(), 1)
                assert worker.submit('second', worker.clock())
                assert not worker.submit('third', worker.clock())
                assert worker.queue.empty()
                assert worker.submit('fresh', worker.clock())
                release.set()
                await asyncio.wait_for(delivered.wait(), 1)
                assert results == ['fresh']
                assert decoded == ['first', 'fresh']
            finally:
                release.set()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
    asyncio.run(run())


@pytest.mark.parametrize('expire_during', [False, True])
def test_expired_transcription_never_reaches_result_handler(expire_during):
    async def run():
        clock = [0 if expire_during else 20]
        discarded = asyncio.Event()
        calls = []
        reasons = []
        def infer(audio):
            calls.append(audio)
            clock[0] = 20
            return 'open calculator'
        async def result(*args):
            pytest.fail('Expired command must not be published')
        async def discard(reason):
            reasons.append(reason)
            discarded.set()
        worker = TranscriptionWorker(infer, result, discard, clock=lambda: clock[0])
        worker.submit('audio', 0)
        task = asyncio.create_task(worker.run())
        try:
            await asyncio.wait_for(discarded.wait(), 1)
            assert ('during' if expire_during else 'before') in reasons[0]
            assert calls == (['audio'] if expire_during else [])
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    asyncio.run(run())


def test_cancelled_transcription_never_publishes_late_native_result():
    from threading import Event
    async def run():
        started = asyncio.Event()
        release = Event()
        loop = asyncio.get_running_loop()
        def infer(audio):
            loop.call_soon_threadsafe(started.set)
            release.wait(2)
            return 'open calculator'
        async def result(*args):
            pytest.fail('Cancelled worker must not publish')
        worker = TranscriptionWorker(infer, result, result)
        worker.submit('audio', worker.clock())
        task = asyncio.create_task(worker.run())
        try:
            await asyncio.wait_for(started.wait(), 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not worker.busy
        finally:
            release.set()
    asyncio.run(run())


def test_audio_driver_reason_survives_segment_rejection():
    engine = segmenter()
    frame = AudioFrame([1, 1], 100, 1, discontinuity=True,
                       discontinuity_reason='audio driver: input overflow')
    result = engine.feed(frame, speech=True, now=100)
    assert 'audio driver: input overflow' in result.discarded_reason
    assert result.blocks is None
