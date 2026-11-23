"""Read keyed Morse from a mono WAV, with full-clip, time-aligned evidence.

Requires NumPy and SciPy. Times in the JSON report are seconds from sample zero.
The frequency is estimated from the recording unless --frequency is supplied.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy import ndimage, signal
from scipy.io import wavfile


SYMBOLS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,?'/()&:;=+-_\"$@!"
PATTERNS = (
    ".- -... -.-. -.. . ..-. --. .... .. .--- -.- .-.. -- -. --- "
    ".--. --.- .-. ... - ..- ...- .-- -..- -.-- --.. "
    "----- .---- ..--- ...-- ....- ..... -.... --... ---.. ----. "
    ".-.-.- --..-- ..--.. .----. -..-. -.--. -.--.- .-... ---... "
    "-.-.-. -...- .-.-. -....- ..--.- .-..-. ...-..- .--.-. -.-.--"
).split()
CODE = dict(zip(PATTERNS, SYMBOLS, strict=True))
CODE.update({"...-.-": "<SK>", "-.-.-": "<KA>", "........": "<HH>"})


def edges(mask):
    changes = np.diff(np.r_[False, mask, False].astype(np.int8))
    return np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)


def carrier(x, rate):
    n = min(len(x), max(128, int(rate * 0.65)))
    frequencies, density = signal.welch(x, rate, nperseg=n)
    band = (frequencies > 120) & (frequencies < min(3500, rate / 2))
    if not np.any(band):
        raise ValueError("Recording too short or sample rate too low to resolve a carrier")
    return float(frequencies[band][np.argmax(density[band])])


def timing(on, off):
    # Allow unequal mark and space weighting from shaped or hand-keyed signals.
    candidates = np.geomspace(.018, .28, 160)
    best = (np.inf, None)
    for unit in candidates:
        short = on[(on > unit * .55) & (on < unit * 1.65)]
        bias = np.clip(np.median(short) - unit, -unit * .24, unit * .24) if len(short) else 0
        mark = np.abs(np.log(on[:, None] / (unit * np.array([1, 3]) + bias))).min(axis=1)
        gap = np.abs(np.log(off / (unit - bias)))
        # Long gaps may have any duration, particularly with Farnsworth spacing.
        loss = np.mean(np.minimum(mark, .53))
        if len(gap):
            loss += .45 * np.minimum(gap, .40).mean()
        if loss < best[0]:
            best = loss, (unit, bias)
    return best[1]


def spacing(gaps, unit, bias):
    letter_cut = 1.95 * unit - bias
    wide = gaps[gaps >= letter_cut]
    if not len(wide):
        return letter_cut, 5 * unit - bias
    normal = wide[wide < 4.7 * unit]
    if len(normal):
        letter = np.median(normal)
    else:
        letter = np.percentile(wide, 25)
    return letter_cut, max(unit * 4.6 - bias, letter * 1.62)


def measured_clock(starts, stops, estimated):
    """Refine a dit estimate using the alignment of both kinds of key edge."""
    # The two edge phases can differ when a transmitter weights its marks.
    # Restrict the edge sample count so long recordings stay inexpensive.
    stride = max(1, len(starts) // 300)
    starts = starts[::stride]
    stops = stops[::stride]
    duration = max(stops[-1] - starts[0], estimated)
    count = int(np.clip(6 * duration / estimated, 120, 20000))
    periods = np.linspace(estimated * .82, estimated * 1.20, count)
    best_period = estimated
    best_strength = -1.
    for chunk in np.array_split(periods, (len(periods) + 255) // 256):
        angle = (2j * np.pi / chunk)[:, None]
        strength = (abs(np.exp(angle * starts).mean(axis=1))
                    + abs(np.exp(angle * stops).mean(axis=1)))
        i = np.argmax(strength)
        if strength[i] > best_strength:
            best_strength = strength[i]
            best_period = chunk[i]
    return best_period


def grid_evidence(frames, rate, unit):
    """Measure complex-amplitude steps and mid-cell tone levels on a dit clock."""
    step = max(1, round(.15 * unit * rate))
    smooth = ndimage.gaussian_filter1d(frames, max(.5, .06 * unit * rate))
    delta = np.roll(smooth, -step) - np.roll(smooth, step)
    delta[:step] = 0
    delta[-step:] = 0
    energy = abs(delta)
    tone = abs(ndimage.gaussian_filter1d(frames, max(.5, .12 * unit * rate)))
    duration = len(frames) / rate

    def sample(values, times):
        indices = np.clip(np.rint(times * rate).astype(int), 0, len(values) - 1)
        return values[indices]

    # Find a lattice origin that places observed transitions on cell boundaries.
    offsets = np.arange(max(2, round(unit * rate))) / rate
    phase = max(offsets, key=lambda v: np.mean(sample(energy, np.arange(v, duration, unit)) ** 1.5)
                if v < duration else -np.inf)
    for parity in (0, 1):
        times = np.arange(phase - (parity + 2) * unit, duration + unit, unit)
        strengths = np.mean([sample(energy, times + unit * k) for k in (-.045, 0, .045)], axis=0)
        levels = np.mean([sample(tone, times + unit * k) for k in (.25, .40, .55, .70)], axis=0)
        strengths[(times < .075 * unit) | (times > duration - .075 * unit)] = 0
        levels[(times < -.55 * unit) | (times >= duration)] = 0
        floor = np.percentile(energy, 35)
        edge_scale = max(np.percentile(strengths, 85) - floor, np.finfo(float).eps)
        low, high = np.percentile(levels, [12, 87])
        tone_scale = max(high - low, np.finfo(float).eps)
        boundary = np.clip((strengths - floor) / edge_scale, -.25, 1.5) - .34
        plateau = np.clip((levels - low) / tone_scale, 0, 1.2) - .38
        yield times, boundary, plateau


def grid_letters(times, boundary, plateau, duration):
    """Fit valid Morse patterns, retaining the time of every chosen transition."""
    n = len(times)
    # Scores are relative to silence. Each dot/dash earns support from both
    # transitions and from the tone within the mark. They are not probabilities.
    scores = {1: boundary[:-1] + boundary[1:] + .6 * plateau[:-1]}
    scores[3] = (boundary[:-3] + boundary[3:]
                 + .6 * (plateau[:-3] + plateau[1:-2] + plateau[2:-1]))
    patterns = []
    for pattern, char in CODE.items():
        offset = 0
        spans = []
        for symbol in pattern:
            width = 1 if symbol == "." else 3
            spans.append((symbol, offset, width))
            offset += width + 1
        length = offset - 1
        if length >= n:
            continue
        placements = sum(scores[w][j:j+n-length] for _, j, w in spans) - .12
        patterns.append((pattern, char, spans, length, placements))

    # One mark plus its following gap always uses an even number of cells.
    # Try the three-unit letter gap and longer word/sentence gaps.
    best = np.full(n + 16, -np.inf)
    best[0:min(n, 24):2] = 0
    previous = {}
    for i in range(0, n, 2):
        if not np.isfinite(best[i]):
            continue
        for pattern, char, spans, length, placements in patterns:
            if i >= len(placements):
                continue
            score = best[i] + placements[i]
            for gap in (3, 7, 9, 11, 13, 15):
                following = i + length + gap
                candidate = score - .08 * max(0, gap - 7)
                if candidate > best[following]:
                    best[following] = candidate
                    previous[following] = (i, char, pattern, spans, gap)
    tail_from = max(0, n - 5)
    tail = tail_from + int(np.argmax(best[tail_from:]))
    score = best[tail]
    letters = []
    while tail in previous:
        i, char, pattern, spans, gap = previous[tail]
        marks = []
        for symbol, offset, width in spans:
            j = i + offset
            start = max(0., times[j])
            end = min(duration, times[j + width])
            if start < end:
                marks.append({"mark": symbol, "start": round(start, 4), "end": round(end, 4),
                              "edge_start_score": round(boundary[j], 3),
                              "edge_end_score": round(boundary[j + width], 3)})
        if marks:
            letters.append({"character": char, "pattern": pattern, "marks": marks,
                            "start": marks[0]["start"], "end": marks[-1]["end"],
                            "word_end": gap >= 7})
        tail = i
    letters.reverse()
    for i, letter in enumerate(letters):
        letter["gap_after"] = round(letters[i+1]["start"] - letter["end"], 4) if i+1 < len(letters) else 0.
    return score, letters


def decode(path, frequency=None, clocked=False, dit_ms=None):
    rate, samples = wavfile.read(path)
    if samples.ndim != 1 or not len(samples):
        raise ValueError("Expected a nonempty mono recording")
    x = samples.astype(np.float64)
    x -= np.mean(x)
    if frequency is not None and not (0 < frequency < rate / 2):
        raise ValueError("Carrier must be positive and below the Nyquist frequency")
    if dit_ms is not None and (not np.isfinite(dit_ms) or dit_ms <= 0):
        raise ValueError("Dit duration must be positive and finite")
    hz = carrier(x, rate) if frequency is None else frequency
    # Mix to baseband before averaging so adjacent tones cancel coherently.
    shift = np.exp((-2j * np.pi * hz / rate) * np.arange(len(x)))
    stride = max(1, round(rate / (1000 if clocked else 500)))
    frames = signal.resample_poly(x * shift, 1, stride)
    frame_rate = rate / stride
    env = abs(ndimage.gaussian_filter1d(frames, frame_rate * .008))
    window = min(len(env) // 2 * 2 + 1, int(frame_rate * 1.6) // 2 * 2 + 1)
    # Estimate the two levels at sparse points, then interpolate through fades.
    index = np.arange(len(env))
    centers = np.unique(np.r_[index[::max(1, int(frame_rate * .12))], index[-1]])
    levels = [np.percentile(env[max(0, i-window//2):i+window//2+1], [12, 87]) for i in centers]
    low, high = (np.interp(index, centers, v) for v in np.asarray(levels).T)
    threshold = low + .46 * (high - low)
    threshold = np.maximum(threshold, np.percentile(env, 86) * .13)
    active = env > threshold
    for target, limit in [(False, .016), (True, .020)]:
        start, end = edges(active == target)
        for a, b in zip(start, end):
            if b - a < frame_rate * limit and (target or (a > 0 and b < len(active))):
                active[a:b] = not target
    start, end = edges(active)
    on = (end-start) / frame_rate
    gap = (start[1:]-end[:-1]) / frame_rate
    result = {"file": Path(path).name, "mode": "clocked" if clocked else "envelope", "frequency_hz": round(hz, 2), "text": "", "letters": []}
    if not len(start):
        return result
    unit, bias = timing(on, gap)
    if dit_ms is not None:
        unit = dit_ms / 1000
    if clocked:
        if dit_ms is None:
            unit = measured_clock(start / frame_rate, end / frame_rate, unit)
        if unit * frame_rate < 4:
            raise ValueError("Dit duration is too short to resolve on the analysis clock")
        duration = len(samples) / rate
        candidates = (grid_letters(times, boundary, plateau, duration)
                      for times, boundary, plateau in grid_evidence(frames, frame_rate, unit))
        _, letters = max(candidates, key=lambda item: item[0])
        result.update(unit_s=round(unit, 6), letters=letters)
        result["text"] = "".join(letter["character"] + (" " if letter["word_end"] else "")
                                 for letter in letters).strip()
        return result
    letter_cut, word_cut = spacing(gap, unit, bias)
    result.update(unit_s=round(unit, 4), mark_bias_s=round(bias, 4),
                  letter_gap_cut_s=round(letter_cut, 4), word_gap_cut_s=round(word_cut, 4))
    marks = []
    for i, (a, b) in enumerate(zip(start, end)):
        symbol = "-" if on[i] >= 2 * unit + bias else "."
        marks.append({"mark": symbol, "start": round(a / frame_rate, 4), "end": round(b / frame_rate, 4)})
        if i == len(gap) or gap[i] >= letter_cut:
            pattern = "".join(m["mark"] for m in marks)
            char = CODE.get(pattern, "#")
            after = 0. if i == len(gap) else gap[i]
            result["letters"].append({"character": char, "pattern": pattern, "start": marks[0]["start"],
                                      "end": marks[-1]["end"], "marks": marks, "gap_after": round(after, 4)})
            result["text"] += char + (" " if after >= word_cut else "")
            marks = []
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", nargs="+", type=Path)
    parser.add_argument("--frequency", type=float, help="Carrier frequency in Hz")
    parser.add_argument("--clocked", action="store_true",
                        help="Fit legal Morse patterns to a periodic clock and complex-signal edges")
    parser.add_argument("--dit-ms", type=float, help="Override the measured dit duration in milliseconds")
    parser.add_argument("--output", type=Path, help="JSON output file (default is standard output)")
    args = parser.parse_args()
    output = json.dumps([decode(path, args.frequency, args.clocked, args.dit_ms) for path in args.wav], indent=2)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
