import asyncio
import json
from types import SimpleNamespace

import pytest
import send_intent


@pytest.mark.parametrize('respond', [True, False])
def test_typed_command_correlates_response_and_closes(monkeypatch, respond):
    class Nats:
        closed = False
        async def connect(self, url, **kwargs):
            assert url == 'nats://localhost:4999'
        async def subscribe(self, subject, cb):
            assert subject == 'ultron.voice'
            self.cb = cb
        async def flush(self):
            pass
        async def publish(self, subject, payload):
            assert subject == 'ultron.intent'
            request = json.loads(payload)
            assert request['prompt'] == 'What is my uptime?'
            for data in [b'invalid', b'[]', b'{"requestId":"another-command"}']:
                await self.cb(SimpleNamespace(data=data))
            if respond:
                await self.cb(SimpleNamespace(data=json.dumps({
                    'requestId': request['requestId'], 'text': 'Uptime: 2 hours.',
                    'execution': {'success': True},
                }).encode()))
        async def close(self):
            self.closed = True
    nc = Nats()
    monkeypatch.setattr(send_intent, 'NATS', lambda: nc)
    monkeypatch.setenv('NATS_URL', 'nats://localhost:4999')
    if respond:
        result = asyncio.run(send_intent.send_command('What is my uptime?', .1))
        assert result['text'] == 'Uptime: 2 hours.'
    else:
        with pytest.raises(TimeoutError):
            asyncio.run(send_intent.send_command('What is my uptime?', .01))
    assert nc.closed
