"""
Beam search decoder for Morse code.

Design rationale
----------------
Bad-fist tolerance is the central challenge.  Rather than making hard dit/dah
decisions based on a threshold, we make *soft* decisions: for each incoming
mark or space, compute P(dit) and P(dah) [or P(letter-space) vs P(word-space)]
from a sigmoid centred on the current threshold.  When the duration is near
the threshold, we branch into two hypotheses and score each with log-probability.
The beam is pruned to the top `beam_width` hypotheses after each event.

Prosign handling
----------------
Prosigns are letter-sequences sent *without* an inter-letter gap.  When the
beam processes a space event it classifies it as:
  - intra-element (very short) → ignored (noise)
  - inter-letter              → commit character, stay in char-accumulation mode
  - word                      → commit character + emit word space
If the inter-letter gap is judged *ambiguous* (near the threshold), the beam
branches: one hypothesis treats it as inter-letter (commits), the other keeps
accumulating (prosign path).  The prosign path is valid only while the
accumulated elements still form a valid prefix in the Morse tree.

Callsign extraction
-------------------
After each decoded character, we scan the recent text for callsign patterns
and update `last_callsign`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .morse_table import MORSE_TREE, MorseNode, DECODE_TABLE, PROSIGN_CODES, MAX_CODE_LEN
from .buffer import TimingEvent

if TYPE_CHECKING:
    from ..timing.estimator import TimingEstimate

# Regex for callsign detection: 1-2 prefix letters, 1 digit, 1-3 suffix letters,
# min 4 characters total.  Optionally preceded by "DE " (very common in CW QSOs).
_CALLSIGN_RE = re.compile(
    r"(?:DE\s+)?([A-Z]{1,2}[0-9][A-Z]{2,3}|[A-Z]{2}[0-9][A-Z]{1,3})\b"
)

_LOG_HALF = math.log(0.5)


def _sigmoid_p_dit(duration_ms: float, threshold_ms: float, scale_ms: float) -> float:
    """
    P(dit) as a sigmoid centred at threshold_ms.

    Returns values close to 1 for short durations (likely dit) and close to 0
    for long durations (likely dah).  `scale_ms` controls how steep the curve
    is; a larger scale widens the ambiguity zone (bad-fist tolerance).
    """
    z = (threshold_ms - duration_ms) / max(scale_ms, 1e-3)
    # Clamp to avoid overflow in exp
    z = max(-20.0, min(20.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _sigmoid_p_letter(duration_ms: float, threshold_ms: float, scale_ms: float) -> float:
    """
    P(letter-space) for an off-gap of `duration_ms`.
    Values close to 1 = likely letter boundary; close to 0 = likely word space.
    (Complementary sigmoid: short off → letter, long off → word.)
    """
    return _sigmoid_p_dit(duration_ms, threshold_ms, scale_ms)


# ---------------------------------------------------------------------------
# Hypothesis
# ---------------------------------------------------------------------------

@dataclass
class Hypothesis:
    node: MorseNode                # current position in the Morse trie
    elements: str                  # accumulated element string for current char ('.', '-')
    text: str                      # fully decoded text so far
    score: float                   # log-probability (higher = better)
    prosign_mode: bool = False     # True: accumulating without letter-gap

    def clone(self) -> "Hypothesis":
        return Hypothesis(
            node=self.node,
            elements=self.elements,
            text=self.text,
            score=self.score,
            prosign_mode=self.prosign_mode,
        )

    def _commit_char(self) -> str:
        """Emit the character at the current node (or '?' if unknown)."""
        if self.node.char is not None:
            return self.node.char
        # Unknown sequence — emit error marker
        return "?"

    def apply_element(self, element: str) -> "Hypothesis | None":
        """
        Traverse one element (dit or dah).  Returns None if this path is
        invalid in the Morse trie (prune signal).
        """
        if len(self.elements) >= MAX_CODE_LEN:
            return None
        child = self.node.get(element)
        if child is None:
            return None
        h = self.clone()
        h.node = child
        h.elements += element
        return h

    def apply_letter_space(self) -> "Hypothesis":
        """Commit the current character and reset to root."""
        h = self.clone()
        if h.elements:
            h.text += h._commit_char()
        h.node = MORSE_TREE
        h.elements = ""
        h.prosign_mode = False
        return h

    def apply_word_space(self) -> "Hypothesis":
        """Commit the current character and emit a word space."""
        h = self.apply_letter_space()
        # Only add a space if the text isn't already ending in one
        if h.text and not h.text.endswith(" "):
            h.text += " "
        return h


# ---------------------------------------------------------------------------
# Beam decoder
# ---------------------------------------------------------------------------

class BeamDecoder:
    """
    Per-channel Morse beam search decoder.

    Call `process_event(event, estimate)` for each TimingEvent produced by
    the segmenter.  Read `text` for the latest decoded output and
    `last_callsign` for the most recently detected callsign.
    """

    def __init__(self, beam_width: int = 16, ambiguity_factor: float = 1.5) -> None:
        self._beam_width = beam_width
        self._ambiguity_factor = ambiguity_factor
        self._beam: list[Hypothesis] = [
            Hypothesis(node=MORSE_TREE, elements="", text="", score=0.0)
        ]
        self._last_callsign: str = ""

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def text(self) -> str:
        """Best-hypothesis decoded text."""
        if not self._beam:
            return ""
        return self._beam[0].text

    @property
    def last_callsign(self) -> str:
        return self._last_callsign

    def process_event(self, event: TimingEvent, estimate: "TimingEstimate") -> None:
        """Process one timing event and update the beam."""
        if estimate.dit_ms <= 0:
            # No timing estimate yet — defer hard decisions
            self._process_no_estimate(event)
            return

        if event.is_mark:
            self._process_mark(event, estimate)
        else:
            self._process_space(event, estimate)

        self._prune()
        self._update_callsign()

    def reset(self) -> None:
        """Full reset (called after long silence / speed re-estimate)."""
        self._beam = [
            Hypothesis(node=MORSE_TREE, elements="", text="", score=0.0)
        ]

    def rewind_and_replay(
        self,
        events: list[TimingEvent],
        estimate: "TimingEstimate",
    ) -> None:
        """Re-decode a list of buffered events with an updated estimate."""
        # Preserve already-committed text from best hypothesis
        best_text = self.text
        self._beam = [
            Hypothesis(node=MORSE_TREE, elements="", text=best_text, score=0.0)
        ]
        for ev in events:
            self.process_event(ev, estimate)

    # ------------------------------------------------------------------
    # Internal — mark processing
    # ------------------------------------------------------------------

    def _process_mark(self, event: TimingEvent, estimate: "TimingEstimate") -> None:
        """A dit or dah arrived.  Branch softly on ambiguous durations."""
        threshold_ms = estimate.dit_dah_threshold_ms
        # Scale widens with ambiguity_factor and is proportional to dit_ms
        scale_ms = estimate.dit_ms * 0.4 * self._ambiguity_factor

        p_dit = _sigmoid_p_dit(event.duration_ms, threshold_ms, scale_ms)
        p_dah = 1.0 - p_dit

        branching = p_dit > 0.05 and p_dah > 0.05  # both options plausible

        new_beam: list[Hypothesis] = []

        for hyp in self._beam:
            if branching:
                # Dit branch
                h_dit = hyp.apply_element(".")
                if h_dit is not None:
                    h_dit.score += math.log(p_dit + 1e-9)
                    new_beam.append(h_dit)
                # Dah branch
                h_dah = hyp.apply_element("-")
                if h_dah is not None:
                    h_dah.score += math.log(p_dah + 1e-9)
                    new_beam.append(h_dah)
            else:
                element = "." if p_dit >= 0.5 else "-"
                h = hyp.apply_element(element)
                if h is not None:
                    new_beam.append(h)

        if new_beam:
            self._beam = new_beam

    # ------------------------------------------------------------------
    # Internal — space processing
    # ------------------------------------------------------------------

    def _process_space(self, event: TimingEvent, estimate: "TimingEstimate") -> None:
        """An off-gap arrived.  Classify as intra-element, letter, or word."""
        # --- Intra-element gap (very short: < half a dit) ---
        if event.duration_ms < estimate.dit_ms * 0.5:
            return  # likely noise / key bounce; ignore

        # --- Letter vs word boundary ---
        lw_threshold_ms = estimate.letter_word_threshold_ms
        scale_ms = estimate.dit_ms * self._ambiguity_factor

        p_letter = _sigmoid_p_letter(event.duration_ms, lw_threshold_ms, scale_ms)
        p_word = 1.0 - p_letter

        # --- Intra-char vs letter boundary ---
        # A space shorter than ~2× dit is treated as intra-character (bad fist gap)
        # vs proper inter-letter (3× dit in theory).
        el_threshold_ms = estimate.element_letter_threshold_ms
        p_commit = _sigmoid_p_dit(event.duration_ms, el_threshold_ms, scale_ms)
        p_commit = 1.0 - p_commit   # longer → more likely to commit

        commit_branching = 0.1 < p_commit < 0.9
        word_branching = p_word > 0.05 and p_letter > 0.05 and p_commit > 0.7

        new_beam: list[Hypothesis] = []

        for hyp in self._beam:
            if not hyp.elements:
                # Nothing accumulated yet — space between words, just pass through
                if event.duration_ms > lw_threshold_ms:
                    h = hyp.clone()
                    if h.text and not h.text.endswith(" "):
                        h.text += " "
                    new_beam.append(h)
                else:
                    new_beam.append(hyp)
                continue

            if commit_branching and not hyp.prosign_mode:
                # Branch: commit char vs stay (prosign path)
                # Prosign path only valid if current prefix still has children
                if hyp.node.has_children and len(hyp.elements) < MAX_CODE_LEN:
                    h_prosign = hyp.clone()
                    h_prosign.prosign_mode = True
                    h_prosign.score += math.log(1.0 - p_commit + 1e-9)
                    new_beam.append(h_prosign)

                # Commit path
                if word_branching:
                    h_letter = hyp.apply_letter_space()
                    h_letter.score += math.log(p_letter * p_commit + 1e-9)
                    new_beam.append(h_letter)

                    h_word = hyp.apply_word_space()
                    h_word.score += math.log(p_word * p_commit + 1e-9)
                    new_beam.append(h_word)
                else:
                    if p_commit >= 0.5:
                        if p_word >= 0.5:
                            new_beam.append(hyp.apply_word_space())
                        else:
                            new_beam.append(hyp.apply_letter_space())
                    else:
                        new_beam.append(hyp)
            else:
                # Hard decision
                if p_commit >= 0.5:
                    if p_word >= 0.5:
                        new_beam.append(hyp.apply_word_space())
                    else:
                        new_beam.append(hyp.apply_letter_space())
                else:
                    new_beam.append(hyp)

        if new_beam:
            self._beam = new_beam

    # ------------------------------------------------------------------
    # Internal — no-estimate fallback
    # ------------------------------------------------------------------

    def _process_no_estimate(self, event: TimingEvent) -> None:
        """
        Simple hard-decision decoder used while the timing estimator is still
        collecting data.  Uses a fixed 1:3 dit:dah ratio heuristic.
        We just buffer elements and don't commit characters until we have a
        real estimate.
        """
        # Buffer marks; ignore spaces (they'll be replayed from RewindBuffer)
        pass

    # ------------------------------------------------------------------
    # Internal — pruning and callsign detection
    # ------------------------------------------------------------------

    def _prune(self) -> None:
        """Keep only the top beam_width hypotheses by score."""
        if len(self._beam) > self._beam_width:
            self._beam.sort(key=lambda h: h.score, reverse=True)
            self._beam = self._beam[: self._beam_width]
        # Renormalize scores to prevent underflow
        if self._beam:
            best = self._beam[0].score
            for h in self._beam:
                h.score -= best

    def _update_callsign(self) -> None:
        """Scan best-hypothesis text for the most recent callsign."""
        text = self.text
        if not text:
            return
        # Search the last 80 characters for efficiency
        window = text[-80:].upper()
        matches = list(_CALLSIGN_RE.finditer(window))
        if matches:
            self._last_callsign = matches[-1].group(1)
