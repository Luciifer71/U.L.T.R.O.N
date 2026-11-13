"""Air-mouse execution in the action daemon (stage G2).

The vision service decides *what* the hand means; this module is the only
place that moves the real mouse. Every command is validated, and nothing
happens unless gesture mode is on (as last announced by the vision service on
``ultron.vision.state``), so a stray message on the bus can never move or
click the mouse when the user is not using gestures.

Moves are not audited (30 a second); clicks, drags and scrolls are, through
the same audit log as every other control action.
"""
from __future__ import annotations

import math
import sys
import time

from .audit import AuditLogger
from .models import AuditRecord
from .policy import CapabilityPolicy

POINTER_SUBJECT = 'ultron.pointer'
VISION_STATE_SUBJECT = 'ultron.vision.state'
OPS = frozenset({'move', 'click', 'down', 'up', 'scroll'})
MAX_SCROLL = 1200  # ten notches per message at most
MAX_COMMANDS_PER_SEC = 120  # well above the 30-60 the vision service sends
# down/up are the pinch pressing and releasing the button (click, double-click or drag).
AUDITED = {'click': 'pointer.click', 'down': 'pointer.button', 'up': 'pointer.button', 'scroll': 'pointer.scroll'}


def parse_command(payload):
    """A validated command dict, or None for anything malformed."""
    if not isinstance(payload, dict):
        return None
    op = payload.get('op')
    if op not in OPS:
        return None
    if op == 'move':
        x, y = payload.get('x'), payload.get('y')
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (x, y)):
            return None
        return {'op': 'move', 'x': min(1.0, max(0.0, float(x))), 'y': min(1.0, max(0.0, float(y)))}
    if op == 'scroll':
        delta = payload.get('delta')
        if not isinstance(delta, int) or isinstance(delta, bool) or delta == 0 or abs(delta) > MAX_SCROLL:
            return None
        return {'op': 'scroll', 'delta': delta}
    return {'op': op}


class WindowsMouse:
    """SendInput-based mouse. Coordinates are fractions of the whole virtual
    desktop (every monitor, any layout), so no DPI or monitor maths is needed."""

    INPUT_MOUSE = 0
    MOVE, LEFTDOWN, LEFTUP, WHEEL = 0x0001, 0x0002, 0x0004, 0x0800
    ABSOLUTE, VIRTUALDESK = 0x8000, 0x4000

    def __init__(self, send=None):
        import ctypes

        # Fixed-width types matching Windows (LONG and DWORD are 32-bit there,
        # ULONG_PTR is pointer-sized): INPUT must be 40 bytes on 64-bit Windows
        # or SendInput silently ignores every event.
        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [('dx', ctypes.c_int32), ('dy', ctypes.c_int32), ('mouseData', ctypes.c_uint32),
                        ('dwFlags', ctypes.c_uint32), ('time', ctypes.c_uint32),
                        ('dwExtraInfo', ctypes.c_size_t)]

        class INPUT(ctypes.Structure):
            class _U(ctypes.Union):
                _fields_ = [('mi', MOUSEINPUT), ('_pad', ctypes.c_byte * 32)]
            _anonymous_ = ('u',)
            _fields_ = [('type', ctypes.c_uint32), ('u', _U)]

        self._ctypes, self._MOUSEINPUT, self._INPUT = ctypes, MOUSEINPUT, INPUT
        self._send = send or ctypes.windll.user32.SendInput

    def _emit(self, flags, dx=0, dy=0, data=0):
        mi = self._MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)
        event = self._INPUT(type=self.INPUT_MOUSE, mi=mi)
        self._send(1, self._ctypes.byref(event), self._ctypes.sizeof(event))

    def move(self, x, y):
        self._emit(self.MOVE | self.ABSOLUTE | self.VIRTUALDESK, round(x * 65535), round(y * 65535))

    def down(self):
        self._emit(self.LEFTDOWN)

    def up(self):
        self._emit(self.LEFTUP)

    def click(self):
        self.down()
        self.up()

    def scroll(self, delta):
        self._emit(self.WHEEL, data=delta)


class PointerController:
    """Applies validated pointer commands while gesture mode is on."""

    def __init__(self, mouse=None, *, audit=None, policy=None, clock=time.monotonic):
        self.mouse = mouse
        self.audit = audit or AuditLogger()
        self.policy = policy or CapabilityPolicy()
        self.clock = clock
        self.gesture_mode = False
        self.pressed = False
        self._window_start = 0.0
        self._window_count = 0

    @classmethod
    def for_this_platform(cls, **kwargs):
        mouse = WindowsMouse() if sys.platform == 'win32' else None
        return cls(mouse, **kwargs)

    def vision_state(self, payload):
        """Track gesture mode from ultron.vision.state; leaving it releases the button."""
        if isinstance(payload, dict) and isinstance(payload.get('gesture'), bool):
            self.gesture_mode = payload['gesture']
            if not self.gesture_mode:
                self.release()

    def release(self):
        if self.pressed and self.mouse is not None:
            self.mouse.up()
            self._record('up', True)
        self.pressed = False

    def _rate_ok(self):
        now = self.clock()
        if now - self._window_start >= 1.0:
            self._window_start, self._window_count = now, 0
        self._window_count += 1
        return self._window_count <= MAX_COMMANDS_PER_SEC

    def handle(self, payload):
        """Apply one command. Returns True if it reached the mouse."""
        command = parse_command(payload)
        if command is None or not self.gesture_mode or self.mouse is None or not self._rate_ok():
            return False
        op = command['op']
        capability = AUDITED.get(op, 'pointer.move')
        if not self.policy.decide(capability).allowed:
            return False
        if op == 'down' and self.pressed:
            return False
        if op == 'up' and not self.pressed:
            return False
        if op == 'move':
            self.mouse.move(command['x'], command['y'])
        elif op == 'scroll':
            self.mouse.scroll(command['delta'])
        else:
            getattr(self.mouse, op)()
            if op in ('down', 'up'):
                self.pressed = op == 'down'
        if op in AUDITED:
            self._record(op, True, command.get('delta'))
        return True

    def _record(self, op, success, delta=None):
        try:
            self.audit.record(AuditRecord(
                task_id='gesture', capability=AUDITED[op], operation=op, target=None, success=success,
                timestamp_ms=AuditLogger.now_ms(),
                metadata={'source': 'air_mouse', **({'delta': delta} if delta is not None else {})}))
        except OSError:
            pass  # auditing must never break input
