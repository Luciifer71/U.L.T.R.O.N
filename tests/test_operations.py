import asyncio
import json
from types import SimpleNamespace

from ultron.agents.brain_agent import PendingAction, UltronBrain
from ultron.control.operations import (
    HEARTBEAT_STALE_SEC, OperationsState, heartbeat_loop, recent_task_rows,
)
from ultron.control.reply_delivery import IntentInbox


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_current_task_steps_and_finish():
    ops = OperationsState(clock=Clock())
    assert ops.request_stop() is None  # Nothing running: nothing to stop.
    ops.begin('t1', 'Open Calculator and Notion')
    ops.stage('t1', 'executing')
    ops.step('t1', 'open:Calculator', 'running')
    ops.step('t1', 'open:Calculator', 'verified')
    ops.step('other', 'open:Notion', 'running')  # Late events for another task are ignored.
    current = ops.snapshot(queued=0, recent=[], services={})['current']
    assert current['stage'] == 'executing'
    assert current['steps'] == [{'name': 'open:Calculator', 'state': 'verified', 'detail': None}]
    assert ops.request_stop() == 't1' and ops.stop_requested('t1')
    ops.finish('t1')
    assert ops.current is None and not ops.stop_requested('t1')


def test_heartbeats_expire_and_ignore_unknown_components():
    clock = Clock()
    ops = OperationsState(clock=clock)
    ops.record_heartbeat(json.dumps({'component': 'listener'}).encode())
    ops.record_heartbeat(b'not json')
    ops.record_heartbeat(json.dumps({'component': 'intruder'}).encode())
    components = ops.components()
    assert components['brain']['online'] and components['listener']['online']
    assert not components['action_daemon']['online'] and 'intruder' not in components
    clock.now += HEARTBEAT_STALE_SEC + 1
    assert not ops.components()['listener']['online']


def test_recent_rows_are_trimmed():
    rows = [{'task_id': 'a', 'prompt': 'x' * 500, 'status': 'failed', 'result_text': None,
             'error_text': '', 'updated_at': '2026-11-09 10:00:00', 'execution_json': '{"big": 1}'}]
    [row] = recent_task_rows(rows)
    assert len(row['prompt']) == 160 and row['error'] is None and 'execution_json' not in row


def test_stop_cancels_remaining_steps_but_keeps_finished_ones(monkeypatch):
    monkeypatch.setattr('ultron.agents.brain_agent.update_task', lambda *a, **k: None)
    monkeypatch.setattr('ultron.agents.brain_agent.EXECUTION_MIN_HOLD_SEC', 0)
    brain = object.__new__(UltronBrain)
    brain.execution_ledger = {}
    brain.operations = OperationsState()
    async def publish_visual(*a, **k):
        return None
    brain._publish_visual = publish_visual
    ran = []
    def first():
        ran.append('first')
        brain.operations.request_stop()  # Stop pressed while step one runs.
        return SimpleNamespace(success=True, message='done', data={'state': 'verified'}, error=None)
    def later():
        ran.append('later')
    brain.operations.begin('task', 'three steps')
    actions = [PendingAction(name='one', execute=first), PendingAction(name='two', execute=later),
               PendingAction(name='three', execute=later)]
    ok, error = asyncio.run(brain._run_pending_actions(actions, 'task'))
    assert ran == ['first'] and ok is False and 'Stopped' in error
    ledger = brain.execution_ledger['task']
    assert [e['state'] for e in ledger] == ['verified', 'cancelled', 'cancelled']
    assert ledger[0]['success'] is True
    assert [s['state'] for s in brain.operations.current['steps']] == ['verified', 'cancelled', 'cancelled']


def test_inbox_clear_pending_drops_only_queued_requests():
    async def run():
        inbox = IntentInbox(brain=None, nc=None, handle=None, classify=None)
        for n in range(3):
            inbox.pending.put_nowait(n)
        assert inbox.clear_pending() == 3
        assert inbox.pending.qsize() == 0 and inbox.clear_pending() == 0
        await asyncio.wait_for(inbox.pending.join(), 1)  # task_done kept the counter balanced
    asyncio.run(run())


def test_heartbeat_loop_publishes_component_and_survives_send_errors():
    sent = []
    class NC:
        is_connected = True
        calls = 0
        async def publish(self, subject, data):
            NC.calls += 1
            if NC.calls == 1:
                raise ConnectionError('blip')
            sent.append((subject, json.loads(data)))
    async def run():
        task = asyncio.create_task(heartbeat_loop(NC(), 'listener', interval=0.01))
        await asyncio.sleep(0.05)
        task.cancel()
    asyncio.run(run())
    assert sent and sent[0] == ('ultron.ops.heartbeat', {'component': 'listener'})


def test_steps_emit_content_free_signals(monkeypatch):
    monkeypatch.setattr('ultron.agents.brain_agent.update_task', lambda *a, **k: None)
    monkeypatch.setattr('ultron.agents.brain_agent.EXECUTION_MIN_HOLD_SEC', 0)
    brain = object.__new__(UltronBrain)
    brain.execution_ledger = {}
    brain.operations = OperationsState()
    sent = []
    brain.signals = SimpleNamespace(emit=lambda kind, payload: sent.append((kind, payload)))
    async def publish_visual(*a, **k):
        return None
    brain._publish_visual = publish_visual
    def ok():
        return SimpleNamespace(success=True, message='done', data={'state': 'verified'}, error=None)
    def bad():
        raise RuntimeError('nope')
    actions = [PendingAction(name='open_resource:Secret App', execute=ok),
               PendingAction(name='open_resource:Other', execute=bad, stop_on_failure=True),
               PendingAction(name='open_resource:Never', execute=ok)]
    asyncio.run(brain._run_pending_actions(actions, 'task'))
    states = [(p['index'], p['state']) for kind, p in sent if kind == 'step']
    assert states == [(0, 'running'), (0, 'verified'), (1, 'running'), (1, 'failed'), (2, 'not_started')]
    assert all(p['total'] == 3 and p['kind'] == 'open_resource' for _, p in sent)
    assert 'Secret' not in json.dumps(sent)
