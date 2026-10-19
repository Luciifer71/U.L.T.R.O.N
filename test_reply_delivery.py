import asyncio
import json
from types import SimpleNamespace
import pytest
from ultron_control.reply_delivery import SpeechQueue, IntentInbox
from ultron_control.google_updates import request_kind, GoogleUpdates


@pytest.mark.parametrize('text', ['What are my latest email updates?', 'Do I have any new emails?',
    'Can you check my recent emails?', 'Tell me about my latest email updates.', 'Update me on my emails.'])
def test_natural_google_requests(text):
    assert request_kind(text) == 'mail'


@pytest.mark.parametrize('text', ['do not check my emails', 'check my emails and delete them',
    'tell me about my emails then open calculator', 'if I ask check my emails', 'send my email updates to someone'])
def test_no_mixed_or_negated_google_requests(text):
    assert request_kind(text) is None


def test_google_lane_bypasses_busy_model_and_stop_bypasses_queue(tmp_path):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        replies = []
        async def handle(msg):
            started.set(); await release.wait()
        async def publish(subject, payload):
            replies.append((subject, json.loads(payload)))
        brain = SimpleNamespace(google_updates=GoogleUpdates(tmp_path))
        inbox = IntentInbox(brain, SimpleNamespace(publish=publish), handle, request_kind)
        msg = lambda text: SimpleNamespace(data=json.dumps({'prompt':text,'requestId':'test'}).encode())
        worker = asyncio.create_task(inbox.run())
        try:
            await inbox.receive(msg('Explain gravity'))
            await asyncio.wait_for(started.wait(), 1)
            await asyncio.wait_for(inbox.receive(msg('What are my latest email updates?')), 0.5)
            assert replies[-1][1]['requestId'] == 'test'
            assert 'Not connected' in replies[-1][1]['text']
            await inbox.receive(msg('stop speaking'))
            assert replies[-2][0] == 'ultron.voice.cancel'
            assert replies[-1][1]['silent'] is True
            assert not release.is_set()
        finally:
            worker.cancel()
            with pytest.raises(asyncio.CancelledError): await worker
    asyncio.run(run())


def test_speech_coalesces_and_expires():
    async def run():
        now, spoken = [0], []
        async def speak(text): spoken.append(text)
        queue = SpeechQueue(speak, clock=lambda: now[0])
        queue.submit('old mail', 'mail', 20)
        queue.submit('new mail', 'mail', 20)
        queue.submit('old calendar', 'calendar', 1)
        now[0] = 2
        worker = asyncio.create_task(queue.run())
        for _ in range(10): await asyncio.sleep(0)
        assert spoken == ['new mail']
        assert not queue.submit('repeat mail', 'mail', 20)
        worker.cancel()
        with pytest.raises(asyncio.CancelledError): await worker
    asyncio.run(run())


def test_cancel_clears_pending_and_stops_current():
    async def run():
        started, cancelled = asyncio.Event(), asyncio.Event()
        spoken = []
        async def speak(text):
            spoken.append(text); started.set()
            try: await asyncio.Event().wait()
            finally: cancelled.set()
        queue = SpeechQueue(speak)
        worker = asyncio.create_task(queue.run())
        queue.submit('current'); queue.submit('pending')
        await asyncio.wait_for(started.wait(), 1)
        await queue.cancel()
        assert cancelled.is_set() and not queue.pending
        assert spoken == ['current']
        worker.cancel()
        with pytest.raises(asyncio.CancelledError): await worker
    asyncio.run(run())


def test_short_voice_keeps_technical_details_out(tmp_path):
    updates = GoogleUpdates(tmp_path)
    updates.enabled = updates.mail_ok = updates.calendar_ok = True
    import time
    updates.checked = time.time(); updates.scanned = 25; updates.important = 4
    updates.calendar_complete = True
    reply = updates.spoken_reply('mail')
    assert '4 potentially important' in reply and '25 reviewed' in reply
    assert len(reply.split()) < 35
    assert 'google_connect.py' not in reply and 'heuristic' not in reply
    assert 'google_connect.py' in updates.reply('mail')


@pytest.mark.parametrize('text', ['What are my latest calendar updates?', 'Check my upcoming appointments.', 'Give me my calendar update for today.'])
def test_natural_calendar_requests(text):
    assert request_kind(text) == 'calendar'
