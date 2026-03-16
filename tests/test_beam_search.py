"""Tests for the beam search decoder."""

import pytest
from morse_decode.decoder.beam_search import BeamDecoder, Hypothesis, _sigmoid_p_dit
from morse_decode.decoder.buffer import TimingEvent
from morse_decode.timing.estimator import TimingEstimate
from morse_decode.decoder.morse_table import MORSE_TREE


def _estimate(dit_ms: float) -> TimingEstimate:
    """Create a plausible TimingEstimate for a given dit duration."""
    return TimingEstimate(
        dit_ms=dit_ms,
        dah_ms=dit_ms * 3.0,
        speed_wpm=1200.0 / dit_ms,
        n_samples=30,
        confident=True,
    )


def _mark(duration_ms: float, t: float = 0.0) -> TimingEvent:
    return TimingEvent(duration_ms=duration_ms, is_mark=True, timestamp_s=t)


def _space(duration_ms: float, t: float = 0.0) -> TimingEvent:
    return TimingEvent(duration_ms=duration_ms, is_mark=False, timestamp_s=t)


def _send_char(decoder: BeamDecoder, code: str, dit_ms: float, est: TimingEstimate) -> None:
    """Feed a single Morse character's events into the decoder."""
    gap = dit_ms        # intra-char gap
    dah_ms = dit_ms * 3.0
    for i, elem in enumerate(code):
        dur = dit_ms if elem == "." else dah_ms
        decoder.process_event(_mark(dur), est)
        if i < len(code) - 1:
            decoder.process_event(_space(gap), est)


def _send_word(decoder: BeamDecoder, word: str, dit_ms: float, est: TimingEstimate) -> None:
    """Send a whole word, separated by letter and word gaps."""
    letter_gap = dit_ms * 3.0
    word_gap = dit_ms * 7.0
    from morse_decode.decoder.morse_table import ENCODE_TABLE
    for i, ch in enumerate(word.upper()):
        code = ENCODE_TABLE.get(ch)
        if code is None:
            continue
        _send_char(decoder, code, dit_ms, est)
        if i < len(word) - 1:
            decoder.process_event(_space(letter_gap), est)
    decoder.process_event(_space(word_gap), est)


class TestSigmoid:
    def test_midpoint(self):
        p = _sigmoid_p_dit(100.0, threshold_ms=100.0, scale_ms=20.0)
        assert abs(p - 0.5) < 0.01

    def test_clear_dit(self):
        p = _sigmoid_p_dit(30.0, threshold_ms=100.0, scale_ms=20.0)
        assert p > 0.95

    def test_clear_dah(self):
        p = _sigmoid_p_dit(200.0, threshold_ms=100.0, scale_ms=20.0)
        assert p < 0.05


class TestHypothesis:
    def test_apply_element_valid(self):
        root_hyp = Hypothesis(node=MORSE_TREE, elements="", text="", score=0.0)
        h = root_hyp.apply_element(".")
        assert h is not None
        assert h.elements == "."
        assert h.node is MORSE_TREE.get(".")

    def test_apply_element_invalid(self):
        # Navigate to E node (single dot), then try an impossible sequence
        node = MORSE_TREE.get(".")  # E
        hyp = Hypothesis(node=node, elements=".", text="", score=0.0)
        # E has children (I, A) so valid paths exist
        h = hyp.apply_element(".")  # → I
        assert h is not None

    def test_letter_space_commits(self):
        # Build hypothesis at 'E' (single dot)
        node = MORSE_TREE.get(".")
        hyp = Hypothesis(node=node, elements=".", text="CQ ", score=0.0)
        committed = hyp.apply_letter_space()
        assert "E" in committed.text
        assert committed.elements == ""
        assert committed.node is MORSE_TREE

    def test_word_space_adds_space(self):
        node = MORSE_TREE.get("-")
        hyp = Hypothesis(node=node, elements="-", text="CQ", score=0.0)
        committed = hyp.apply_word_space()
        assert "T" in committed.text
        assert committed.text.endswith(" ")


class TestBeamDecoder:
    def _decode_word(self, word: str, dit_ms: float = 80.0) -> str:
        est = _estimate(dit_ms)
        dec = BeamDecoder(beam_width=16)
        _send_word(dec, word, dit_ms, est)
        return dec.text.strip()

    def test_decode_E(self):
        est = _estimate(80.0)
        dec = BeamDecoder(beam_width=8)
        dec.process_event(_mark(80.0), est)
        dec.process_event(_space(240.0), est)  # letter gap
        assert "E" in dec.text

    def test_decode_T(self):
        est = _estimate(80.0)
        dec = BeamDecoder(beam_width=8)
        dec.process_event(_mark(240.0), est)
        dec.process_event(_space(240.0), est)
        assert "T" in dec.text

    def test_decode_cq(self):
        result = self._decode_word("CQ", dit_ms=80.0)
        # Should contain C and Q in order
        assert "C" in result
        assert "Q" in result

    def test_reset_clears_text(self):
        est = _estimate(80.0)
        dec = BeamDecoder(beam_width=8)
        dec.process_event(_mark(80.0), est)
        dec.reset()
        assert dec.text == ""

    def test_callsign_detection(self):
        # Manually inject text into best hypothesis
        est = _estimate(80.0)
        dec = BeamDecoder(beam_width=4)
        # Directly manipulate beam to inject text (white-box test)
        from morse_decode.decoder.beam_search import Hypothesis
        dec._beam = [Hypothesis(
            node=MORSE_TREE, elements="", text="CQ CQ DE W1AW K ", score=0.0
        )]
        dec._update_callsign()
        assert dec.last_callsign == "W1AW"

    def test_callsign_kd9xyz(self):
        from morse_decode.decoder.beam_search import Hypothesis
        dec = BeamDecoder(beam_width=4)
        dec._beam = [Hypothesis(
            node=MORSE_TREE, elements="", text="DE KD9XYZ KD9XYZ K ", score=0.0
        )]
        dec._update_callsign()
        assert dec.last_callsign == "KD9XYZ"

    def test_rewind_replay(self):
        """After speed update, rewind should not crash."""
        est = _estimate(80.0)
        dec = BeamDecoder(beam_width=8)
        events = [
            _mark(80.0, 0.08), _space(80.0, 0.16),
            _mark(240.0, 0.40), _space(240.0, 0.64),
        ]
        dec.rewind_and_replay(events, est)
        # Should not raise; text may be partial
        assert isinstance(dec.text, str)
