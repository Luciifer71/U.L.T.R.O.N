"""One Euro filter: removes webcam jitter without adding lag to fast moves.

Casiez, Roussel and Vogel, "1€ Filter: A Simple Speed-based Low-pass Filter for
Noisy Input in Interactive Systems" (CHI 2012). Slow movement is smoothed
heavily (no shaking pointer); fast movement is smoothed lightly (no lag).
"""
import math


def _alpha(cutoff, dt):
    tau = 1.0 / (2 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class OneEuroFilter:
    def __init__(self, min_cutoff=1.2, beta=0.02, d_cutoff=1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.value = None
        self.derivative = 0.0
        self.last_time = None

    def reset(self):
        self.value = None
        self.derivative = 0.0
        self.last_time = None

    def __call__(self, x, t):
        if self.value is None or self.last_time is None or t <= self.last_time:
            self.value, self.last_time = x, t
            return x
        dt = t - self.last_time
        self.last_time = t
        dx = (x - self.value) / dt
        a_d = _alpha(self.d_cutoff, dt)
        self.derivative += a_d * (dx - self.derivative)
        cutoff = self.min_cutoff + self.beta * abs(self.derivative)
        self.value += _alpha(cutoff, dt) * (x - self.value)
        return self.value


class LandmarkFilter:
    """One Euro filter for all 21×3 coordinates of one hand."""

    def __init__(self, min_cutoff=1.2, beta=0.02):
        self.filters = [OneEuroFilter(min_cutoff, beta) for _ in range(63)]

    def reset(self):
        for f in self.filters:
            f.reset()

    def __call__(self, landmarks, t):
        flat = [float(v) for p in landmarks for v in p[:3]]
        out = [f(v, t) for f, v in zip(self.filters, flat)]
        return [out[i:i + 3] for i in range(0, 63, 3)]
