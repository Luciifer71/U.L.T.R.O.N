import numpy as np
import pytest
from speech_activity import SpeechActivity
from audio_pipeline import AudioFrame, UtteranceSegmenter


def test_loud_non_speech_can_finish_an_utterance_without_truncation():
    scores = iter([0.8] * 4 + [0.1] * 22)
    detector = SpeechActivity(lambda audio: np.full(32, next(scores)))
    segmenter = UtteranceSegmenter(sample_rate=16000, silence_seconds=1.4,
        max_seconds=15, preroll_blocks=8, max_backlog_seconds=2)
    results = []
    for i in range(26):
        # Constant RMS above the user's 0.016 threshold would never finish.
        samples = np.full(1024, 0.04, dtype=np.float32)
        frame = AudioFrame(samples, 1, i)
        results.append(segmenter.feed(frame, speech=detector.classify(samples), now=1))
    assert all(r.blocks is None for r in results[:-1])
    assert len(results[-1].blocks) == 26


def test_speech_hysteresis_and_reset_do_not_drop_low_energy_speech():
    scores = iter([0.6, 0.4, 0.2, 0.4])
    detector = SpeechActivity(lambda audio: np.full(32, next(scores)))
    quiet = np.full(1024, 0.001, dtype=np.float32)
    assert detector.classify(quiet)
    assert detector.classify(quiet)
    assert not detector.classify(quiet)
    detector.reset()
    assert not detector.classify(quiet)
    assert len(detector.history) == 16384


@pytest.mark.parametrize('prediction', [np.full(32, np.nan), np.ones(2), np.full(32, 1.5)])
def test_invalid_detection_is_an_error_not_a_false_silence(prediction):
    detector = SpeechActivity(lambda audio: prediction)
    with pytest.raises(ValueError): detector.classify(np.ones(1024))


def test_predictor_cannot_mutate_captured_audio_or_history():
    def predict(audio):
        audio[:] = 0
        return np.zeros(32)
    detector = SpeechActivity(predict)
    samples = np.ones(1024, dtype=np.float32)
    detector.classify(samples)
    assert np.all(samples == 1) and np.all(detector.history[-1024:] == 1)


def test_real_bundled_silero_handles_silence_and_stationary_noise():
    pytest.importorskip('faster_whisper')
    from faster_whisper.vad import get_vad_model
    detector = SpeechActivity(get_vad_model())
    assert not detector.classify(np.zeros(1024, dtype=np.float32))
    rng = np.random.default_rng(42)
    votes = [detector.classify(rng.normal(0, 0.04, 1024).astype(np.float32)) for _ in range(32)]
    assert not any(votes[-22:])
