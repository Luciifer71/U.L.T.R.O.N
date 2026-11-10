"""Turning gesture mode on and off: voice phrases and a double clap.

Both are deliberately conservative. A voice request must be a whole command
("gesture mode on", "activate gestures"...), never a word inside another
sentence. A double clap must be two short, sharp, loud sounds 0.15-0.8 s apart
with quiet around them, which ordinary speech, typing or music rarely produce.
"""
import math
import re

CONTROL_SUBJECT = 'ultron.vision.control'
STATE_SUBJECT = 'ultron.vision.state'

_PREFIX = r"(?:(?:hey|ok(?:ay)?)[, ]+)?(?:ultron[, ]+)?(?:please[, ]+)?(?:(?:can|could|would) you[, ]+)?"
_ON = (
    r"(?:turn on|switch on|start|enable|activate|enter|open) (?:the )?(?:gesture|gestures|hand)(?: mode| control| tracking)?",
    r"(?:gesture|gestures|hand)(?: mode| control| tracking)? (?:on|start|activate)",
    r"gesture mode",
    r"(?:show|watch) my hands",
)
_OFF = (
    r"(?:turn off|switch off|stop|disable|deactivate|exit|leave|close) (?:the )?(?:gesture|gestures|hand)(?: mode| control| tracking)?",
    r"(?:gesture|gestures|hand)(?: mode| control| tracking)? (?:off|stop)",
)


def gesture_command(prompt):
    """'gesture_on', 'gesture_off' or None for a whole spoken/typed request."""
    if not isinstance(prompt, str) or len(prompt) > 120:
        return None
    text = re.sub(r"\s+", " ", prompt.strip().lower().rstrip('.!?')).strip()
    for pattern in _OFF:
        if re.fullmatch(_PREFIX + pattern + r"(?: please)?(?: now)?", text):
            return 'gesture_off'
    for pattern in _ON:
        if re.fullmatch(_PREFIX + pattern + r"(?: please)?(?: now)?", text):
            return 'gesture_on'
    return None


def _peak_rms(samples):
    if hasattr(samples, 'dtype'):  # NumPy array from the listener: vectorised
        import numpy as np
        flat = np.asarray(samples, dtype=np.float32).ravel()
        return float(np.max(np.abs(flat))), float(np.sqrt(np.mean(flat * flat))) or 1e-9
    values = [float(s) for s in samples]
    return max(abs(v) for v in values), math.sqrt(sum(v * v for v in values) / len(values)) or 1e-9


class DoubleClapDetector:
    """Detects two claps in a row from microphone blocks (float samples, -1..1).

    A clap is a block whose peak is far above the room's background level and
    whose energy is concentrated in a sharp spike (high crest factor), followed
    quickly by quiet. Two claps between ``min_gap`` and ``max_gap`` seconds apart
    trigger once; a refractory period prevents repeats.
    """

    def __init__(self, min_gap=0.15, max_gap=0.8, refractory=2.0, peak_over_noise=8.0,
                 min_peak=0.25, min_crest=4.0):
        self.min_gap = min_gap
        self.max_gap = max_gap
        self.refractory = refractory
        self.peak_over_noise = peak_over_noise
        self.min_peak = min_peak
        self.min_crest = min_crest
        self.noise = 0.01
        self.last_clap = None
        self.last_trigger = -math.inf
        self.loud_blocks = 0

    def update(self, samples, now, muted=False):
        """Feed one block. Returns True exactly when a double clap completes."""
        if muted or samples is None or len(samples) == 0:
            self.loud_blocks = 0
            return False
        peak, rms = _peak_rms(samples)
        crest = peak / rms
        is_spike = peak >= self.min_peak and peak >= self.noise * self.peak_over_noise and crest >= self.min_crest
        if not is_spike:
            # Track the background level slowly, only from non-clap blocks.
            self.noise = 0.98 * self.noise + 0.02 * max(rms, 1e-4)
            self.loud_blocks = 0 if peak < self.noise * self.peak_over_noise else self.loud_blocks + 1
            return False
        self.loud_blocks += 1
        if self.loud_blocks > 2:
            return False  # sustained loud sound (speech, music), not a clap
        if now - self.last_trigger < self.refractory:
            return False
        if self.last_clap is not None and self.min_gap <= now - self.last_clap <= self.max_gap:
            self.last_clap = None
            self.last_trigger = now
            return True
        self.last_clap = now
        return False
