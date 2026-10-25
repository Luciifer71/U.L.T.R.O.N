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


@pytest.mark.parametrize('text, expected', [
    ('Can you brief me about my latest email updates?', 'mail'),
    ('Is there any later latest calendar updates?', 'calendar'),
    ('Okay, please summarize my inbox.', 'mail'),
    ('Give me both my email and calendar updates.', 'all'),
    ('What is on my calendar today?', 'calendar'),
    ('Tell me about my emails then open calculator', 'clarify'),
    ('Check my calendar next week', 'clarify'),
    ('Read the email from Alice', 'clarify'),
    ('Delete my emails', 'unsupported'),
    ('Check my emails and delete them', 'unsupported'),
    ('Send my email updates to someone', 'unsupported'),
    ('Do not check my emails', None),
    ('If I ask check my emails', None),
    ('"check my emails"', None),
    ('Explain gravity', None),
    ('Open calculator', None),
    ('email ' * 1000, None),
])
def test_google_routing_contract(text, expected):
    from ultron_control.google_routing import route_request
    assert route_request(text) == expected


@pytest.mark.parametrize('kind', ['mail', 'calendar', 'all'])
def test_google_status_states(tmp_path, kind):
    import time
    service = GoogleUpdates(tmp_path)
    assert 'Not connected' in service.spoken_reply(kind)
    service.enabled = True
    assert 'Waiting for the first successful sync' in service.spoken_reply(kind)
    service.status = 'Google sync unavailable. Reconnect if access was revoked or expired.'
    assert 'unavailable' in service.spoken_reply(kind)
    service.checked = time.time()
    assert 'unavailable' in service.spoken_reply(kind)
    assert '0 events' not in service.spoken_reply(kind)
    service.mail_ok = service.calendar_ok = True
    service.complete = service.calendar_complete = True
    reply = service.spoken_reply(kind)
    assert 'unavailable' not in reply
    assert '0' in reply
    service.complete = service.calendar_complete = False
    assert any(word in service.spoken_reply(kind) for word in ['progress', 'partial'])
    service.checked -= 900
    assert 'minutes old' in service.spoken_reply(kind)


def test_routing_batch_stays_out_of_model_queue(tmp_path):
    from ultron_control.google_routing import route_request
    async def run():
        replies = []
        async def handle(msg): pytest.fail('Google request reached model')
        async def publish(subject, payload): replies.append(json.loads(payload))
        inbox = IntentInbox(SimpleNamespace(google_updates=GoogleUpdates(tmp_path)),
                            SimpleNamespace(publish=publish), handle, route_request)
        phrases = ['Can you brief me about my latest email updates?',
                   'Is there any later latest calendar updates?',
                   'Check my calendar next week', 'Delete my emails']
        for i in range(200):
            msg = SimpleNamespace(data=json.dumps({'prompt': phrases[i % 4], 'requestId': str(i)}).encode())
            await inbox.receive(msg)
        assert inbox.pending.empty()
        assert len(replies) == 200
        assert [r['requestId'] for r in replies] == [str(i) for i in range(200)]
        assert all('cannot access' not in r['text'] for r in replies)
    asyncio.run(run())


@pytest.mark.parametrize('prompt', [
    'Give me calendar updates as well as what are my system stats',
    'Check my calendar and show my system stats',
    'Can you give me calendar updates and also what are my system stats?',
])
def test_combined_google_and_system_reads(prompt, monkeypatch):
    from ultron_control import read_requests as reads
    kinds = reads.read_request_kinds(prompt)
    assert kinds == ('google-calendar', 'telemetry')
    monkeypatch.setattr(reads, 'collect_telemetry', lambda: {'cpu_percent': 12, 'memory_percent': 60})
    google = SimpleNamespace(spoken_reply=lambda kind: 'Calendar sync is unavailable.')
    reply = reads.read_request_reply(kinds, google)
    assert 'Calendar sync is unavailable' in reply and 'CPU: 12%' in reply
    def broken(kind): raise RuntimeError('private token')
    google.spoken_reply = broken
    reply = reads.read_request_reply(kinds, google)
    assert 'unavailable' in reply and 'CPU: 12%' in reply and 'private token' not in reply


@pytest.mark.parametrize('prompt', ['check my calendar and delete my files',
    'do not check my calendar and system stats', '"check my calendar" and system stats',
    'open calculator and system stats', 'system stats and system stats and system stats and system stats and system stats'])
def test_read_composition_never_swallows_other_actions(prompt):
    from ultron_control.read_requests import read_request_kinds
    assert read_request_kinds(prompt) is None


def test_capability_and_combined_reads_bypass_busy_model(tmp_path, monkeypatch):
    from ultron_control import read_requests as reads
    from ultron_control.google_routing import route_request
    monkeypatch.setattr(reads, 'collect_telemetry', lambda: {'cpu_percent': 7})
    async def run():
        replies = []
        async def handle(msg): pytest.fail('local request reached model')
        async def publish(subject, payload): replies.append(json.loads(payload))
        inbox = IntentInbox(SimpleNamespace(google_updates=GoogleUpdates(tmp_path)),
                            SimpleNamespace(publish=publish), handle, route_request)
        for prompt in ['what all tasks can you do for me?', 'Hey Ultron, Hey Ultron,',
                       'check my calendar and what are my system stats']:
            await inbox.receive(SimpleNamespace(data=json.dumps({'prompt':prompt, 'requestId':prompt}).encode()))
        assert inbox.pending.empty()
        assert 'named applications' in replies[0]['text']
        assert 'listening' in replies[1]['text']
        assert 'Not connected' in replies[2]['text'] and 'CPU: 7%' in replies[2]['text']
    asyncio.run(run())
