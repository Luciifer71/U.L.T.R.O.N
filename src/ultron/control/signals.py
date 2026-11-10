"""Live signals for the visual entity, published on ``ultron.signal.<kind>``.

The UI uses these to make the entity react to what ULTRON is really doing:
task steps, the user's voice level, model inference and system load. They are
display hints only:

* fire-and-forget: a failed publish never affects a task;
* content-free: no prompts, transcripts, file paths or app names, only
  numbers, step positions, action kinds and outcomes;
* never acted on: the action daemon does not subscribe to ``ultron.signal.*``.
"""
import asyncio
import json
import logging
import math
import time

SIGNAL_PREFIX = 'ultron.signal.'
STEP_STATES = frozenset({'running', 'verified', 'completed', 'dispatched', 'failed', 'cancelled', 'not_started'})
VOICE_RATE_HZ = 15.0
VITALS_INTERVAL_SEC = 2.0

logger = logging.getLogger('ultron.signals')


class SignalPublisher:
    """Schedules small JSON publishes without awaiting or raising."""

    def __init__(self, nc):
        self.nc = nc
        self._pending = set()

    def emit(self, kind, payload):
        if not getattr(self.nc, 'is_connected', False):
            return False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
        data = json.dumps(payload, separators=(',', ':')).encode()
        task = loop.create_task(self._publish(SIGNAL_PREFIX + kind, data))
        # Keep a reference until done so the task is not garbage collected.
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        return True

    async def _publish(self, subject, data):
        try:
            await self.nc.publish(subject, data)
        except Exception as error:  # Display hints must never break callers.
            logger.debug('signal publish failed: %s', type(error).__name__)


def step_signal(task_id, index, total, name, state):
    """Step progress without the step's target (which may name private files or apps)."""
    kind = str(name).split(':', 1)[0][:40]
    return {
        'taskId': str(task_id),
        'index': max(0, int(index)),
        'total': max(1, int(total)),
        'kind': kind,
        'state': state if state in STEP_STATES else 'completed',
    }


class VoiceLevelMeter:
    """Turns microphone RMS into a throttled 0..1 level while the user speaks.

    Levels are reported at most ``rate_hz`` times a second, plus one final 0 when
    speech stops, so the UI's ripple settles instead of freezing mid-motion.
    """

    def __init__(self, rate_hz=VOICE_RATE_HZ, clock=time.monotonic):
        self.interval = 1.0 / rate_hz
        self.clock = clock
        self.last_sent = -math.inf
        self.active = False

    @staticmethod
    def level(rms, threshold):
        if threshold <= 0 or rms <= threshold:
            return 0.0
        # Logarithmic: a whisper and a shout both read clearly.
        return round(min(1.0, math.log2(rms / threshold) / 4.0), 3)

    def update(self, rms, threshold, speaking):
        """Return a level to publish now, or None to stay quiet."""
        now = self.clock()
        if not speaking:
            if self.active:
                self.active = False
                self.last_sent = now
                return 0.0
            return None
        if now - self.last_sent < self.interval:
            return None
        self.active = True
        self.last_sent = now
        return self.level(rms, threshold)


def read_vitals(psutil_module=None):
    """CPU and memory use as 0..1 fractions, or None if psutil is unavailable."""
    try:
        psutil = psutil_module or __import__('psutil')
        cpu = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory().percent
    except Exception:
        return None
    return {'cpu': round(min(max(cpu / 100.0, 0.0), 1.0), 3), 'memory': round(min(max(memory / 100.0, 0.0), 1.0), 3)}


async def vitals_loop(publisher, interval=VITALS_INTERVAL_SEC, reader=read_vitals):
    """Publish system load every ``interval`` seconds until cancelled."""
    reader()  # The first cpu_percent(None) call only primes the measurement.
    while True:
        await asyncio.sleep(interval)
        vitals = await asyncio.to_thread(reader)
        if vitals is not None:
            publisher.emit('vitals', vitals)


class ModelActivity:
    """Reports when the language model starts and finishes a request.

    Nested or overlapping requests are counted, so ``end`` is reported only when
    the last one finishes.
    """

    def __init__(self, publisher, clock=time.monotonic):
        self.publisher = publisher
        self.clock = clock
        self.active = 0
        self.started = 0.0

    def start(self):
        self.active += 1
        if self.active == 1:
            self.started = self.clock()
            self.publisher.emit('model', {'phase': 'start'})

    def end(self):
        if self.active == 0:
            return
        self.active -= 1
        if self.active == 0:
            seconds = round(self.clock() - self.started, 2)
            self.publisher.emit('model', {'phase': 'end', 'seconds': seconds})
