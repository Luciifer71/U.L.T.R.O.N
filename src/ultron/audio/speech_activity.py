"""Bounded rolling speech detection using Faster-Whisper's bundled Silero model."""
import logging
import numpy as np


class SpeechActivity:
    def __init__(self, predictor):
        self.predictor = predictor
        self.reset()

    def reset(self):
        self.history = np.zeros(16384, dtype=np.float32)
        self.active = False

    def classify(self, samples):
        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        if len(samples) != 1024 or not np.isfinite(samples).all():
            raise ValueError('Speech detector requires 1024 finite samples at 16 kHz')
        self.history = np.concatenate((self.history[len(samples):], samples))
        # The upstream predictor uses a mutable context view: never hand it
        # capture buffers or our retained history. It runs on a worker thread.
        probabilities = np.asarray(self.predictor(self.history.copy())).reshape(-1)
        if len(probabilities) != 32 or not np.isfinite(probabilities).all():
            raise ValueError('Speech detector returned invalid probabilities')
        if np.any((probabilities < 0) | (probabilities > 1)):
            raise ValueError('Speech probabilities out of range')
        probability = float(np.max(probabilities[-2:]))
        self.active = probability >= (0.35 if self.active else 0.5)
        return self.active


def create_speech_activity():
    try:
        from faster_whisper.vad import get_vad_model
        detector = SpeechActivity(get_vad_model())
        detector.classify(np.zeros(1024, dtype=np.float32))
        detector.reset()
        logging.info('[SPEECH DETECTOR]: Silero active; speech boundaries use speech probability, not RMS alone')
        return detector
    except Exception as exc:
        logging.warning('[SPEECH DETECTOR]: unavailable (%s); using legacy RMS detection', exc)
        return None
