"""Operations dashboard state: current task, cooperative stop and heartbeats.

The dashboard reads this through NATS request/reply on ``ultron.ops.status``.
Nothing here executes actions; ``request_stop`` only asks the brain to stop
before the next step of the current task. A step already running is allowed
to finish and nothing is undone.
"""
import asyncio
import json
import time

OPS_PREFIX = 'ultron.ops.'
STATUS_SUBJECT = 'ultron.ops.status'
STOP_SUBJECT = 'ultron.ops.stop'
HEARTBEAT_SUBJECT = 'ultron.ops.heartbeat'
HEARTBEAT_INTERVAL_SEC = 5.0
# A component counts as offline after missing about three heartbeats.
HEARTBEAT_STALE_SEC = 16.0
COMPONENTS = ('listener', 'action_daemon', 'vision')
_TEXT_LIMIT = 300


def _short(value, limit=_TEXT_LIMIT):
    text = ' '.join(str(value or '').split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


class OperationsState:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.current = None
        self._stop_task_id = None
        self.heartbeats = {}

    # -- current task ---------------------------------------------------
    def begin(self, task_id, prompt):
        self.current = {'taskId': task_id, 'prompt': _short(prompt), 'stage': 'received',
                        'startedAt': self.clock(), 'steps': []}

    def stage(self, task_id, stage):
        if self.current and self.current['taskId'] == task_id:
            self.current['stage'] = stage

    def step(self, task_id, name, state, detail=None):
        if not self.current or self.current['taskId'] != task_id:
            return
        steps = self.current['steps']
        for entry in steps:
            if entry['name'] == name and entry['state'] == 'running':
                entry['state'], entry['detail'] = state, _short(detail, 160) if detail else None
                return
        steps.append({'name': _short(name, 120), 'state': state,
                      'detail': _short(detail, 160) if detail else None})
        del steps[:-20]

    def finish(self, task_id):
        if self.current and self.current['taskId'] == task_id:
            self.current = None
        if self._stop_task_id == task_id:
            self._stop_task_id = None

    # -- stop -----------------------------------------------------------
    def request_stop(self):
        """Mark the current task for a stop before its next step."""
        if not self.current:
            return None
        self._stop_task_id = self.current['taskId']
        self.current['stage'] = 'stopping'
        return self._stop_task_id

    def stop_requested(self, task_id):
        return task_id is not None and self._stop_task_id == task_id

    # -- heartbeats -----------------------------------------------------
    def record_heartbeat(self, data):
        try:
            payload = json.loads(data)
        except (ValueError, UnicodeError):
            return
        component = payload.get('component') if isinstance(payload, dict) else None
        if component in COMPONENTS:
            self.heartbeats[component] = self.clock()

    def components(self):
        now = self.clock()
        result = {'brain': {'online': True, 'lastSeen': now}}
        for name in COMPONENTS:
            seen = self.heartbeats.get(name)
            result[name] = {'online': seen is not None and now - seen <= HEARTBEAT_STALE_SEC,
                            'lastSeen': seen}
        return result

    def snapshot(self, *, queued, recent, services):
        return {'observedAt': self.clock(), 'components': self.components(),
                'services': services, 'current': self.current, 'queued': queued,
                'recent': recent}


def recent_task_rows(rows):
    """Reduce stored task rows to what the dashboard shows."""
    result = []
    for row in rows:
        result.append({'taskId': row.get('task_id'), 'prompt': _short(row.get('prompt'), 160),
                       'status': row.get('status'), 'result': _short(row.get('result_text'), 200),
                       'error': _short(row.get('error_text'), 200) or None,
                       'updatedAt': row.get('updated_at')})
    return result


async def heartbeat_loop(nc, component, interval=HEARTBEAT_INTERVAL_SEC):
    """Publish a small liveness message until cancelled. Never raises on a send failure."""
    payload = json.dumps({'component': component}).encode()
    while True:
        try:
            if nc.is_connected:
                await nc.publish(HEARTBEAT_SUBJECT, payload)
        except Exception:
            pass  # Missing heartbeats are how the dashboard shows the problem.
        await asyncio.sleep(interval)
