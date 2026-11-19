const MORSE = Object.fromEntries([
  ...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('').map((letter, i) =>
    ['.- -... -.-. -.. . ..-. --. .... .. .--- -.- .-.. -- -. --- .--. --.- .-. ... - ..- ...- .-- -..- -.-- --..'.split(' ')[i], letter]),
  ...'0123456789'.split('').map((digit, i) =>
    ['----- .---- ..--- ...-- ....- ..... -.... --... ---.. ----.'.split(' ')[i], digit]),
  ['.-.-.-', '.'], ['--..--', ','], ['..--..', '?'], ['-..-.', '/'],
  ['-....-', '-'], ['.--.-.', '@'], ['.-.-.', '<AR>'], ['-...-', '<BT>'],
  ['-.--.', '<KN>'], ['.-...', '<AS>'], ['-.-.-', '<CT>'], ['...-.', '<SN>'],
  ['...-.-', '<SK>'], ['...---...', '<SOS>']
]);

const minCarrierScore = 5;

function quantile(sorted, fraction) {
  return sorted[Math.floor((sorted.length - 1) * fraction)];
}

function select(values, fraction) {
  // Partition a scratch copy so spectrum updates do not sort whole histories.
  const wanted = Math.floor((values.length - 1) * fraction);
  let low = 0;
  let high = values.length - 1;
  while (low < high) {
    const pivot = values[(low + high) >>> 1];
    let left = low;
    let right = high;
    while (left <= right) {
      while (values[left] < pivot) left++;
      while (values[right] > pivot) right--;
      if (left <= right) {
        const value = values[left];
        values[left++] = values[right];
        values[right--] = value;
      }
    }
    if (wanted <= right) high = right;
    else if (wanted >= left) low = left;
    else break;
  }
  return values[wanted];
}

function durationCost(length, expected) {
  return logCost(Math.log(length / expected));
}

function logCost(logError) {
  const error = Math.abs(logError);
  return error < 0.35 ? error * error / 0.7 : error - 0.175;
}

const logThree = Math.log(3);

function estimateClock(history, dt, minUnit, maxUnit) {
  // With regular sending, both rising and falling edges recur on a dot grid.
  // The spectral peak of squared slopes survives some false and missing edges.
  const edges = [];
  let mass = 0;
  for (let i = 2; i < history.length - 2; i++) {
    const slope = Math.abs(history[i + 2] - history[i - 2]);
    const weight = slope * slope;
    edges.push(weight);
    mass += weight;
  }
  if (!mass) return null;
  let peak = 0.18;
  let unit = null;
  const upper = Math.min(60, 0.45 / dt, 1 / (minUnit * dt));
  for (let frequency = 1 / (maxUnit * dt); frequency < upper; frequency += 0.19) {
    const angular = 2 * Math.PI * dt * frequency;
    const c = Math.cos(angular);
    const s = Math.sin(angular);
    let real = 0;
    let imag = 0;
    let x = 1;
    let y = 0;
    for (const edge of edges) {
      real += edge * x;
      imag += edge * y;
      const next = x * c - y * s;
      y = y * c + x * s;
      x = next;
    }
    const score = Math.hypot(real, imag) / mass - 0.0013 * frequency;
    if (score > peak) {
      peak = score;
      unit = 1 / (frequency * dt);
    }
  }
  return unit;
}

function bestUnit(runs, grid, previous, clockUnit) {
  const max = grid.at(-1).unit;
  const usable = runs.filter(({on, length}) => on || length < (previous || max) * 4.8).slice(-48);
  if (usable.filter(run => run.on).length < 3) return previous;
  let best = previous;
  let bestCost = Infinity;
  const logPrevious = previous ? Math.log(previous) : null;
  const logClock = clockUnit ? Math.log(clockUnit) : null;
  for (const {unit, logUnit} of grid) {
    let cost = logPrevious === null ? 0 : 0.065 * usable.length * Math.abs(logUnit - logPrevious);
    if (logClock !== null) cost += 0.28 * usable.length * Math.abs(logUnit - logClock);
    for (const {on, logLength} of usable) {
      const error = logLength - logUnit;
      const one = logCost(error);
      const three = logCost(error - logThree);
      cost += Math.min(on ? 0.8 : 0.45, one, three);
    }
    if (cost < bestCost) {
      bestCost = cost;
      best = unit;
    }
  }
  return best;
}

const patterns = Object.entries(MORSE);

function estimateTiming(runs, unit, signalDb) {
  const cluster = (on, low, high, expected) => {
    if (signalDb < 20) return expected;
    const lengths = runs.filter(run => run.on === on && run.length >= unit * low && run.length <= unit * high)
      .map(run => run.length).sort((a, b) => a - b);
    return lengths.length < 6 ? expected : 0.44 * expected + 0.56 * quantile(lengths, 0.5);
  };
  const timing = {
    dot: cluster(true, 0.60, 1.66, unit),
    dash: cluster(true, 1.84, 5.30, 3 * unit),
    element: cluster(false, 0.45, 1.69, unit)
  };
  const gaps = runs.filter(run => !run.on && run.length > 1.75 * unit && run.length < 22 * unit);
  if (gaps.length < 4) return {...timing, letter: unit * 3, ready: false};
  let best = 3;
  let bestCost = Infinity;
  for (let ratio = 2.45; ratio <= 8.5; ratio += 0.10) {
    let cost = 0.034 * gaps.length * Math.abs(Math.log(ratio / 3));
    for (const {length} of gaps) {
      cost += Math.min(0.29, durationCost(length, ratio * unit),
        0.045 + durationCost(length, 7 / 3 * ratio * unit));
    }
    if (cost < bestCost) {
      bestCost = cost;
      best = ratio;
    }
  }
  const hasExtendedLetters = best >= 4 && gaps.filter(({length}) => length > best * unit * 0.82 && length < best * unit * 1.22).length >= 3;
  const hasExtendedWords = gaps.some(({length}) => length >= best * unit * 1.85);
  const extended = hasExtendedLetters && hasExtendedWords;
  const standard = gaps.some(({length}) => length < 4.1 * unit);
  return {...timing, letter: (extended ? best : 3) * unit, ready: extended || standard};
}

function makeDecimator(factor) {
  const radius = 6 * factor;
  const cutoff = 0.43 / factor;
  const weights = Float64Array.from({length: 2 * radius + 1}, (_, i) => {
    const offset = i - radius;
    const window = 0.42 + 0.5 * Math.cos(Math.PI * offset / radius)
      + 0.08 * Math.cos(2 * Math.PI * offset / radius);
    return window * (offset ? Math.sin(2 * Math.PI * cutoff * offset) / (Math.PI * offset) : 2 * cutoff);
  });
  return {factor, weights, delay: radius, history: new Float64Array(2 * weights.length), index: 0, phase: 0};
}

function hann(length) {
  return Float64Array.from({length}, (_, i) => 0.5 - 0.5 * Math.cos(2 * Math.PI * i / (length - 1)));
}

function coherentPowers(iq, phaseStep, dt) {
  // A keyed oscillator can hold phase across silences. Fit its offset from
  // the search bin and project onto that phasor to reject quadrature noise.
  const length = iq.length / 2;
  const phasors = new Float64Array(iq.length);
  let energy = 0;
  for (let i = 0; i < length; i++) {
    const cos = Math.cos(i * phaseStep);
    const sin = Math.sin(i * phaseStep);
    const real = iq[2 * i];
    const imag = iq[2 * i + 1];
    phasors[2 * i] = real * cos + imag * sin;
    phasors[2 * i + 1] = imag * cos - real * sin;
    energy += Math.hypot(real, imag);
  }
  let fit = {strength: 0};
  for (let hz = -9; hz <= 9; hz += 1.5) {
    const step = 2 * Math.PI * hz * dt;
    let real = 0;
    let imag = 0;
    for (let i = 0; i < length; i++) {
      const cos = Math.cos(i * step);
      const sin = Math.sin(i * step);
      real += phasors[2 * i] * cos + phasors[2 * i + 1] * sin;
      imag += phasors[2 * i + 1] * cos - phasors[2 * i] * sin;
    }
    const strength = Math.hypot(real, imag);
    if (strength > fit.strength) fit = {strength, step, phase: Math.atan2(imag, real)};
  }
  // Fall back to ordinary power for phase resets and unstable fits.
  if (fit.strength <= 0.51 * energy) return null;
  return Float64Array.from({length}, (_, i) => {
    const angle = fit.phase + i * fit.step;
    const real = phasors[2 * i];
    const imag = phasors[2 * i + 1];
    const projected = Math.max(0, real * Math.cos(angle) + imag * Math.sin(angle));
    return 0.15 * (real * real + imag * imag) + 0.85 * projected * projected;
  });
}

function decodeWord(marks, timing) {
  const costs = marks.map(({length, gap}) => [durationCost(length, timing.dot), durationCost(length, timing.dash),
    durationCost(gap, timing.element), durationCost(gap, timing.letter)]);
  const paths = [{cost: 0, text: ''}];
  for (let i = 0; i < marks.length; i++) {
    for (const [pattern, char] of patterns) {
      const end = i + pattern.length;
      if (end > marks.length) continue;
      let cost = paths[i].cost;
      for (let j = i; j < end; j++) {
        cost += costs[j][pattern[j - i] === '.' ? 0 : 1];
        if (j < marks.length - 1) cost += costs[j][j === end - 1 ? 3 : 2];
      }
      if (!paths[end] || cost < paths[end].cost) paths[end] = {cost, text: paths[i].text + char};
    }
  }
  return paths[marks.length].text;
}

function decodeWords(marks, timing) {
  const words = [];
  let start = 0;
  for (let i = 0; i < marks.length; i++) {
    if (i + 1 < marks.length && marks[i].gap <= timing.letter * 1.57) continue;
    words.push(decodeWord(marks.slice(start, i + 1), timing));
    start = i + 1;
  }
  return words;
}

class CWDecoder {
  constructor(sampleRate, {
    low = 400, high = 1000, minWpm = 5, maxWpm = 50, binWidth = 12,
    windowMs = 50, hopMs = 5, debounceMs = 2, onDb = 24, offDb = 20,
    agcEnabled = false, agcWindowS = 10, agcTargetRms = 0.1,
    guard = false, includeHigh = true
  } = {}) {
    if (!(Number.isFinite(sampleRate) && low >= 0 && high > low && high < sampleRate / 2 &&
        minWpm > 0 && Number.isFinite(maxWpm) && minWpm < maxWpm &&
        Number.isFinite(binWidth) && binWidth >= 1)) {
      throw new RangeError('Choose a passband below half the sample rate, a positive bin width, and a valid WPM range.');
    }
    // Leave transition bandwidth above the highest search and guard tone.
    const highestTone = high + (guard ? Math.max(48, binWidth) : 0);
    const factor = Math.max(1, Math.floor(sampleRate / Math.max(4000, 3.2 * highestTone)));
    const analysisRate = sampleRate / factor;
    if (factor > 1) this.decimator = makeDecimator(factor);
    this.hop = Math.round(analysisRate * hopMs / 1000);
    const windowLength = Math.round(analysisRate * windowMs / 1000);
    if (!(this.hop > 0 && Number.isFinite(windowLength) && windowLength > this.hop &&
        Number.isFinite(debounceMs) && debounceMs >= 0 && Number.isFinite(offDb) &&
        Number.isFinite(onDb) && offDb < onDb)) {
      throw new RangeError('Check the analysis window, hop, debounce, and detection thresholds.');
    }
    this.dt = this.hop / analysisRate;
    this.lobeWidth = analysisRate / windowLength;
    this.debounceFrames = Math.max(2, Math.ceil(debounceMs / (1000 * this.dt)));
    this.updateFrames = Math.max(1, Math.round(0.16 / this.dt));
    this.acquisitionFrames = Math.max(2, Math.round(1.28 / this.dt));
    this.finalFrames = Math.max(2, Math.round(0.10 / this.dt));
    this.lookaheadFrames = Math.round(0.14 / this.dt);
    this.historyFrames = Math.max(this.acquisitionFrames, Math.round(3.84 / this.dt));
    // Keep the terminal controls on their historical 24/20 scale while
    // applying both thresholds to the same adaptive noise reference.
    this.onGain = 4 * (4 / 2.8) ** ((onDb - 24) / 4);
    this.offGain = 2.8 * (4 / 2.8) ** ((offDb - 20) / 4);
    this.minUnit = 1.2 / maxWpm / this.dt;
    this.maxUnit = 1.2 / minWpm / this.dt;
    if (!Number.isFinite(this.maxUnit) || this.minUnit === 0) {
      throw new RangeError('The WPM range is too wide for the analysis hop.');
    }
    this.unitGrid = [];
    for (let unit = this.minUnit; unit <= this.maxUnit * 1.001; unit *= 1.025) {
      this.unitGrid.push({unit, logUnit: Math.log(unit)});
    }
    // A 50 ms Hann window gives weak carriers more separation from noise.
    this.window = hann(windowLength);
    this.shortWindow = hann(Math.max(3, Math.round(windowLength * 0.64)));
    this.longWindow = hann(Math.round(windowLength * 1.38));
    this.recording = new Float64Array((this.historyFrames + this.updateFrames) * this.hop + 3 * this.longWindow.length);
    this.writeIndex = 0;
    this.sampleCount = 0;
    this.audio = new Float64Array(this.window.length);
    this.windowed = new Float64Array(this.window.length);
    if (agcEnabled) {
      if (!(Number.isFinite(agcWindowS) && agcWindowS > 0 && agcTargetRms > 0 && agcTargetRms <= 1)) {
        throw new RangeError('Choose a positive AGC time constant and target RMS between 0 and 1.');
      }
      this.agc = {
        alpha: -Math.expm1(-1 / (agcWindowS * sampleRate)),
        target: agcTargetRms,
        meanSquare: agcTargetRms ** 2
      };
    }
    this.fill = 0;
    const bins = Math.ceil((high - low) / binWidth);
    const step = (high - low) / bins;
    const frequencies = Array.from({length: bins + 1}, (_, i) => low + i * step);
    this.bandSize = bins + Number(includeHigh);
    this.guard = guard;
    // Inspect neighbouring frequencies to avoid decoding the skirts of a
    // stronger carrier outside this passband as another station.
    if (guard) {
      const guardStep = Math.max(6, step);
      for (let offset = guardStep; offset <= Math.max(48, guardStep); offset += guardStep) {
        if (low - offset >= 0) frequencies.push(low - offset);
        if (high + offset < sampleRate / 2) frequencies.push(high + offset);
      }
    }
    this.tones = frequencies.map(hz => ({hz, coeff: 2 * Math.cos(2 * Math.PI * hz / analysisRate), history: []}));
    this.frame = 0;
    this.cursor = 0;
    this.selected = null;
    this.active = false;
    this.signalDb = null;
    this.callsign = '';
    this.unit = null;
    this.timing = null;
    this.clockUnit = null;
    this.previousGuess = null;
    this.text = '';
    this.runs = [];
    this.marks = [];
    this.state = false;
    this.run = 0;
    this.pending = 0;
    this.keyClock = 0;
    this.markPeak = 0;
    this.markEnd = 0;
    this.wordSeen = false;
  }

  push(samples) {
    if (this.decimator) {
      const filter = this.decimator;
      const {weights, history, factor} = filter;
      const size = weights.length;
      const reduced = new Float64Array(Math.floor((samples.length + filter.phase) / factor));
      let output = 0;
      for (const value of samples) {
        const sample = this.gainSample(value);
        history[filter.index] = sample;
        history[filter.index + size] = sample;
        if (++filter.index === size) filter.index = 0;
        if (++filter.phase !== factor) continue;
        filter.phase = 0;
        let filtered = 0;
        for (let tap = 0; tap < size; tap++) filtered += weights[tap] * history[filter.index + tap];
        reduced[output++] = filtered;
      }
      this.pushAnalysis(reduced);
    } else {
      this.pushAnalysis(samples, Boolean(this.agc));
    }
  }

  gainSample(sample) {
    const agc = this.agc;
    if (!agc) return sample;
    agc.meanSquare += agc.alpha * (sample ** 2 - agc.meanSquare);
    return sample * Math.min(100, agc.target / Math.max(1e-5, Math.sqrt(agc.meanSquare)));
  }

  pushAnalysis(samples, applyGain = false) {
    for (let offset = 0; offset < samples.length;) {
      const n = Math.min(this.audio.length - this.fill, samples.length - offset);
      if (applyGain) {
        for (let i = 0; i < n; i++) {
          this.audio[this.fill + i] = this.gainSample(samples[offset + i]);
        }
      } else {
        this.audio.set(samples.subarray(offset, offset + n), this.fill);
      }
      for (let i = 0; i < n; i++) {
        this.recording[this.writeIndex++] = this.audio[this.fill + i];
        if (this.writeIndex === this.recording.length) this.writeIndex = 0;
      }
      this.sampleCount += n;
      this.fill += n;
      offset += n;
      if (this.fill === this.audio.length) {
        this.analyze();
        this.audio.copyWithin(0, this.hop);
        this.fill -= this.hop;
      }
    }
  }

  analyze() {
    for (let i = 0; i < this.audio.length; i++) this.windowed[i] = this.audio[i] * this.window[i];
    for (const tone of this.tones) {
      let s1 = 0;
      let s2 = 0;
      for (let i = 0; i < this.windowed.length; i++) {
        const s = this.windowed[i] + tone.coeff * s1 - s2;
        s2 = s1;
        s1 = s;
      }
      tone.history.push(Math.max(0, s1 * s1 + s2 * s2 - tone.coeff * s1 * s2));
    }
    this.frame++;
    if (this.frame % this.updateFrames === 0) this.processFrames();
  }

  tonePower(frame, coeff, window, iq, offset) {
    const start = frame * this.hop + Math.round((this.window.length - window.length) / 2);
    let index = (start + this.recording.length) % this.recording.length;
    let s1 = 0;
    let s2 = 0;
    for (let i = 0; i < window.length; i++) {
      const sample = start + i >= 0 && start + i < this.sampleCount ? this.recording[index] : 0;
      const s = sample * window[i] + coeff * s1 - s2;
      s2 = s1;
      s1 = s;
      if (++index === this.recording.length) index = 0;
    }
    if (iq) {
      const cosine = coeff * 0.5;
      iq[offset] = s1 - cosine * s2;
      iq[offset + 1] = Math.sqrt(Math.max(0, 1 - cosine * cosine)) * s2;
    }
    return Math.max(0, s1 * s1 + s2 * s2 - coeff * s1 * s2);
  }

  processFrames(final = false) {
    const length = this.tones[0].history.length;
    if (length < (final ? this.finalFrames : this.acquisitionFrames)) return;

    const levels = this.tones.map(tone => {
      const powers = tone.history.slice();
      return {floor: select(powers, 0.20), peak: select(powers, 0.86), crest: select(powers, 0.94)};
    });
    const typical = levels.slice(0, this.bandSize).map(level => level.floor).sort((a, b) => a - b);
    const background = Math.max(1e-13, quantile(typical, 0.45));
    const contrast = ({floor, peak}) => peak - floor;
    const score = level => contrast(level) / (level.floor + 2 * background);
    // Among plausible keyed carriers, prefer a stronger peak as well as a
    // larger normalized contrast. A steady tone has little contrast.
    const strength = level => {
      const ratio = score(level);
      return ratio > minCarrierScore ? Math.sqrt(ratio * (level.crest - level.floor) / background) : ratio;
    };
    let best = 0;
    for (let i = 0; i < this.bandSize; i++) {
      if (strength(levels[i]) > strength(levels[best])) best = i;
    }
    const inBand = index => {
      if (!this.guard) return true;
      const contrast = levels[index].peak - levels[index].floor;
      const hz = this.tones[index].hz;
      for (let i = 0; i < levels.length; i++) {
        const distance = Math.abs(this.tones[i].hz - hz);
        const outsideLobe = i >= this.bandSize || distance >= this.lobeWidth;
        if (outsideLobe && distance <= 48 && levels[i].peak - levels[i].floor > contrast) return false;
      }
      return true;
    };
    const current = this.selected === null ? null : levels[this.selected];
    const shouldSwitch = !current || (score(levels[best]) > 2.5 * score(current) &&
      !this.state && this.run > (this.unit || this.maxUnit) * 8);
    if (shouldSwitch && score(levels[best]) > minCarrierScore && inBand(best)) {
      if (this.selected !== null && Math.abs(this.selected - best) > 2) {
        this.commitWord();
        this.unit = null;
        this.timing = null;
        this.clockUnit = null;
        this.previousGuess = null;
        this.runs = [];
        this.pending = 0;
      }
      this.selected = best;
    } else if (current) {
      // Follow Doppler and oscillator drift one bin at a time. A local
      // spectral measurement follows the transmission sooner than the
      // longer history used to distinguish a carrier from a noise peak.
      const selected = this.selected;
      const recent = index => {
        const powers = this.tones[index].history.slice(-Math.round(0.56 / this.dt));
        const floor = Math.max(levels[index].floor, select(powers, 0.18));
        const peak = select(powers, 0.84);
        return {contrast: peak - floor, score: score({floor, peak})};
      };
      const present = recent(selected);
      let nextScore = Math.max(4.9, present.score * 1.15);
      for (const index of [selected - 1, selected + 1]) {
        if (index < 0 || index >= this.bandSize || !inBand(index) || contrast(levels[index]) < contrast(current) * 0.5) continue;
        const candidate = recent(index);
        if (candidate.score <= nextScore || candidate.contrast < present.contrast * 1.18) continue;
        this.selected = index;
        nextScore = candidate.score;
      }
    }
    const startFrame = this.frame - length;
    const endFrame = this.frame - (final ? 0 : this.lookaheadFrames);
    if (this.selected !== null) {
      this.processKeying(levels, background, score(levels[this.selected]), inBand(this.selected), startFrame, endFrame);
      this.cursor = endFrame;
    }
    if (length > this.historyFrames) {
      const trim = length - this.historyFrames;
      for (const tone of this.tones) tone.history.splice(0, trim);
    }
  }

  processKeying(levels, background, carrierScore, withinBand, startFrame, endFrame) {
    let {floor, peak} = levels[this.selected];
    const strong = carrierScore > minCarrierScore && withinBand;
    this.active = strong;
    this.signalDb = 10 * Math.log10(1 + carrierScore);
    const length = this.frame - startFrame;
    const start = Math.max(0, this.cursor - startFrame);
    const tone = this.tones[this.selected];
    let history = tone.history;
    let noiseBackground = background;
    if (this.frame % (4 * this.updateFrames) === 0) {
      const guess = carrierScore < 16 && length * this.dt > 2.2
        ? estimateClock(history, this.dt, this.minUnit, this.maxUnit) : null;
      this.clockUnit = guess && this.previousGuess && Math.abs(guess / this.previousGuess - 1) < 0.07 ? guess : null;
      this.previousGuess = guess;
    }
    const isolated = !this.guard && !this.tones.some((other, index) =>
      Math.abs(other.hz - tone.hz) > this.lobeWidth * 1.9 && levels[index].peak > peak * 0.14);
    // A short window preserves fast elements. A long one trades time
    // resolution for more rejection of noise near a weak carrier.
    const window = carrierScore > 150 && isolated
      ? this.shortWindow : carrierScore < 10 ? this.longWindow : null;
    const coherent = (carrierScore < 35 || isolated && carrierScore < 150) && withinBand;
    if (window || coherent) {
      const from = Math.max(0, Math.min(start - Math.ceil(0.45 / this.dt), length - this.acquisitionFrames));
      const measured = new Float64Array(length);
      const iq = coherent ? new Float64Array(2 * (length - from)) : null;
      const filter = window || this.window;
      for (let i = from; i < length; i++) {
        measured[i] = this.tonePower(startFrame + i, tone.coeff, filter, iq, 2 * (i - from));
      }
      const projected = coherent && coherentPowers(iq, 2 * Math.PI * tone.hz * this.dt, this.dt);
      if (window || projected) {
        if (projected) measured.set(projected, from);
        history = measured;
        const powers = history.slice(from);
        floor = select(powers, 0.20);
        peak = select(powers, 0.86);
        noiseBackground *= filter.length / this.window.length * (projected ? 1.9 : 1);
      }
    }
    const range = peak - floor;
    const envelope = new Float64Array(length);
    const localPeak = new Float64Array(length);
    const decay = Math.exp(-this.dt / 0.072);
    let crest = 0;
    for (let i = Math.max(0, start - Math.ceil(0.45 / this.dt)); i < length; i++) {
      envelope[i] = (history[Math.max(0, i - 1)] + 2 * history[i] + history[Math.min(length - 1, i + 1)]) / 4;
      crest = Math.max(crest * decay, envelope[i]);
      localPeak[i] = crest;
    }
    crest = 0;
    // Look both ways within the available audio so the key threshold can
    // follow a fade without rising late at the first returning dit.
    for (let i = length - 1; i >= start; i--) {
      crest = Math.max(crest * decay, envelope[i]);
      localPeak[i] = Math.max(crest, localPeak[i]);
    }
    const probes = this.tones.filter((tone, index) => {
      const distance = Math.abs(tone.hz - this.tones[this.selected].hz);
      return distance >= 2.1 * this.lobeWidth && distance <= 220 &&
        levels[index].peak < 14 * (background + levels[index].floor);
    });
    const adaptToFade = isolated && carrierScore > 55;
    for (let i = start; i < endFrame - startFrame; i++) {
      const localContrast = Math.max(0.044 * range, Math.min(range, localPeak[i] - floor));
      const gain = this.state ? this.offGain : this.onGain;
      let transient = 0;
      for (const tone of probes) transient += Math.min(tone.history[i], 40 * background);
      transient /= probes.length || 1;
      const noise = Math.max(noiseBackground + floor, (transient - 6 * background) * 0.28);
      // After a word-sized gap, keep a little of the session-wide reference.
      // Otherwise the decaying crest can turn idle noise into an extra dit.
      const idle = !this.state && this.unit && this.keyClock - this.markEnd > 4.5 * this.unit;
      const relative = adaptToFade ? Math.max(localContrast, idle ? range * 0.11 : 0) : range;
      const gate = floor + Math.max(gain * noise, relative * (this.state ? 0.075 : 0.14));
      this.keyFrame((this.state || strong) && envelope[i] > gate,
        (envelope[i] - floor) / Math.max(1e-13, noise * this.onGain), adaptToFade, carrierScore < 9.5);
    }
  }

  keyFrame(on, confidence, rejectSpikes, weak) {
    this.keyClock++;
    if (on) this.markPeak = Math.max(this.markPeak, confidence);
    else if (!this.state) this.markPeak = 0;
    this.run++;
    if (on === this.state) {
      this.pending = 0;
    } else {
      this.pending++;
      const debounce = this.state
        ? Math.max(this.debounceFrames, Math.round((this.unit || this.minUnit) * 0.37))
        : this.debounceFrames;
      if (this.pending >= debounce) {
        const length = this.run - this.pending;
        if (this.state) {
          this.storeMark(length, this.keyClock - this.pending, rejectSpikes, weak);
          this.markPeak = 0;
        }
        this.run = this.pending;
        this.pending = 0;
        this.state = on;
      }
    }
    if (!this.state && !this.pending && this.marks.length &&
        this.keyClock - this.markEnd > Math.max(this.maxUnit * 4, (this.timing?.letter || 0) * 2.5)) this.commitWord();
  }

  storeMark(length, end, rejectSpikes, weak) {
    if (weak && length * this.dt < 0.031 && this.markPeak < 2.10) return;
    const minimum = rejectSpikes && this.markPeak < 1.65 ? 0.80 : 0.40;
    if (length < Math.max(this.minUnit * 0.65, (this.unit || 0) * minimum)) return;
    if (this.marks.length) {
      // Measure silence between accepted marks so a rejected click cannot
      // split a letter or word gap into two shorter pieces.
      const gap = end - length - this.markEnd;
      this.marks.at(-1).gap = gap;
      this.remember(false, gap);
      this.updateTiming();
      if ((this.timing?.ready && gap > 1.57 * this.timing.letter) || this.marks.length >= 120) this.commitWord();
    }
    this.marks.push({length, gap: 0});
    this.markEnd = end;
    this.remember(true, length);
  }

  remember(on, length) {
    if (length <= 0) return;
    this.runs.push({on, length, logLength: Math.log(length)});
    if (this.runs.length > 64) this.runs.shift();
  }

  updateTiming() {
    this.unit = bestUnit(this.runs, this.unitGrid, this.unit, this.clockUnit);
    if (this.unit) this.timing = estimateTiming(this.runs.slice(-48), this.unit, this.signalDb);
  }

  commitWord() {
    if (!this.marks.length) return;
    this.updateTiming();
    const unit = this.unit || this.marks[0].length;
    const words = decodeWords(this.marks, this.timing || {dot: unit, dash: 3 * unit, element: unit, letter: 3 * unit});
    this.text += (this.wordSeen ? ' ' : '') + words.join(' ');
    for (const word of words) {
      if (/^(?:[A-Z]{1,2}\d[A-Z]{2,3}|[A-Z]{2}\d[A-Z])$/.test(word)) this.callsign = word;
    }
    this.wordSeen = true;
    this.marks = [];
  }

  snapshot() {
    const preview = this.timing && this.marks.length ? decodeWords(this.marks, this.timing).join(' ') : '';
    return {
      text: this.text,
      preview: this.text && preview ? ' ' + preview : preview,
      frequency: this.selected === null ? null : this.tones[this.selected].hz,
      wpm: this.unit ? 1.2 / (this.dt * this.unit) : null,
      callsign: this.callsign,
      signalDb: this.signalDb,
      active: this.active
    };
  }

  finish() {
    if (this.decimator) this.push(new Float64Array(this.decimator.delay));
    this.pushAnalysis(new Float64Array(Math.floor(this.window.length / 2)));
    this.processFrames(true);
    if (this.state) {
      const length = this.run - this.pending;
      this.storeMark(length, this.keyClock - this.pending, false);
      this.state = false;
    }
    this.commitWord();
    return this.snapshot();
  }
}

export {CWDecoder, MORSE};
