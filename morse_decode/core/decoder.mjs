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

function bestUnit(runs, grid, previous, clockUnit, isolatedReceiver) {
  const max = grid.at(-1).unit;
  const usable = runs.filter(({on, length}) => on || length < (previous || max) * 4.8).slice(-48);
  if (usable.filter(run => run.on).length < 3) return previous;
  const periods = [];
  if (runs.length <= 32) {
    // A low threshold lengthens a mark and shortens the next space. The
    // interval between their rising edges still measures two or four dits.
    const gaps = runs.filter(run => !run.on).map(run => run.length).sort((a, b) => a - b);
    const shortGap = quantile(gaps, 0.30);
    for (let i = 1; i < runs.length; i++) {
      if (!runs[i].on && runs[i].length <= 1.55 * shortGap) {
        periods.push(Math.log((runs[i - 1].length + runs[i].length) / 2));
      }
    }
  }
  // A run of equally weighted dots can initially fit an all-dash clock
  // at twice the speed. Two rising-edge interval clusters resolve the octave.
  let logKeyedUnit = null;
  if (isolatedReceiver && periods.length >= 4) {
    const ordered = periods.slice().sort((a, b) => a - b);
    const short = quantile(ordered, 0.35);
    const dots = ordered.filter(period => Math.abs(period - short) < 0.16);
    const dashes = ordered.filter(period => Math.abs(period - short - Math.LN2) < 0.16);
    if (dots.length >= 3 && dashes.length && dots.length + dashes.length >= 0.8 * ordered.length) {
      logKeyedUnit = quantile(dots, 0.5);
    }
  }
  let best = previous;
  let bestCost = Infinity;
  const logPrevious = previous ? Math.log(previous) : null;
  const logClock = clockUnit ? Math.log(clockUnit) : null;
  for (const {unit, logUnit} of grid) {
    let cost = logPrevious === null ? 0 : 0.065 * usable.length * Math.abs(logUnit - logPrevious);
    if (logKeyedUnit !== null) cost += 0.45 * usable.length * Math.min(0.55, Math.abs(logKeyedUnit - logUnit));
    if (logClock !== null) cost += 0.28 * usable.length * Math.abs(logUnit - logClock);
    for (const {on, logLength} of usable) {
      const error = logLength - logUnit;
      const one = logCost(error);
      const three = logCost(error - logThree);
      cost += Math.min(on ? 0.8 : 0.45, one, three);
    }
    for (const period of periods) {
      const error = period - logUnit;
      cost += 0.55 * Math.min(0.45, logCost(error), logCost(error - Math.LN2));
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
    if (signalDb < 12) return expected;
    const lengths = runs.filter(run => run.on === on && run.length >= unit * low && run.length <= unit * high)
      .map(run => run.length).sort((a, b) => a - b);
    return lengths.length < 6 ? expected : 0.44 * expected + 0.56 * quantile(lengths, 0.5);
  };
  const timing = {
    // At high contrast each edge is already well resolved. In noise,
    // give extra weight to the interval between successive rising edges.
    onsetWeight: signalDb < 27 ? 2 : 0,
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

function regularKeying(runs, unit) {
  if (!unit || runs.length < 10) return false;
  // Consecutive onsets in a machine-keyed word are an even number of
  // dits apart. Fit the period from these intervals even during a fade.
  const intervals = [];
  for (let i = 1; i < runs.length; i++) {
    if (runs[i].on || runs[i].length > 4.3 * unit) continue;
    const period = runs[i - 1].length + runs[i].length;
    const count = 2 * Math.round(period / (2 * unit));
    if (count >= 2 && count <= 8) intervals.push({period, count});
  }
  if (intervals.length < 5) return false;
  const fitted = select(intervals.map(({period, count}) => period / count), 0.5);
  const aligned = intervals.filter(({period, count}) => Math.abs(period / fitted - count) <= 0.20);
  return aligned.length >= 0.88 * intervals.length;
}

function fadedKeyingGrid(history, {floor, peak}, runs, unit) {
  // A constant key weight shifts all mark lengths by a similar amount. Look
  // for scattered lengths after removing that bias, as a selective fade can
  // make a threshold crossing move within an otherwise clocked transmission.
  const errors = runs.filter(run => run.on).map(({length}) =>
    length / unit - (length < 1.95 * unit ? 1 : 3));
  if (errors.length < 8) return null;
  const bias = select(errors, 0.5);
  if (errors.filter(error => Math.abs(error - bias) > 0.2).length < 0.18 * errors.length) return null;

  // Compare strong marks across several groups before using their level as
  // a reference for a weak one. It becomes unreliable during a gain change.
  const span = Math.max(1, Math.round(12 * unit));
  if (history.length < 2 * span) return null;
  let lowest = Infinity;
  let highest = 0;
  for (let end = history.length; end >= span; end -= span) {
    const level = select(history.slice(end - span, end), 0.88);
    lowest = Math.min(lowest, level);
    highest = Math.max(highest, level);
  }
  if (lowest < 0.5 * highest) return null;

  const edges = [];
  const first = Math.max(0, history.length - Math.round(42 * unit));
  const threshold = floor + 0.19 * (peak - floor);
  for (let i = first + 1; i < history.length; i++) {
    const before = history[i - 1];
    const after = history[i];
    if ((before > threshold) === (after > threshold)) continue;
    edges.push(i - 1 + (threshold - before) / (after - before));
  }
  if (edges.length < 14 || edges.at(-1) - edges[0] < 24 * unit) return null;

  // Rising edges recur at even dit counts and falling edges at odd counts.
  // Their signed sum gives both the period and the phase of the keying.
  let grid = null;
  let best = 0.67 * edges.length;
  for (let step = 0; step <= 25; step++) {
    const period = unit * (0.9 + step * 0.008);
    const angle = Math.PI / period;
    let real = 0;
    let imag = 0;
    let sign = history[first] > threshold ? -1 : 1;
    for (const edge of edges) {
      real += sign * Math.cos(edge * angle);
      imag += sign * Math.sin(edge * angle);
      sign = -sign;
    }
    const strength = Math.hypot(real, imag);
    if (strength > best) {
      best = strength;
      grid = {period, origin: Math.atan2(imag, real) / angle};
    }
  }
  return grid && Math.abs(grid.period / unit - 1) < 0.09 ? grid : null;
}

function wordBoundary(runs, unit, letter) {
  const standard = 1.57 * letter;
  const gaps = runs.filter(run => !run.on).map(run => run.length);
  // A hand-keyed dah and the pauses between letters can both run long.
  // A three-dit letter reference would split callsigns and single words.
  const dashes = runs.filter(run => run.on && run.length > 1.8 * unit).map(run => run.length);
  const spaces = gaps.filter(gap => gap > 1.8 * unit && gap < 16 * unit);
  if (spaces.length >= 3 && dashes.length >= 3 && select(dashes, 0.5) > 3.4 * unit) {
    const usual = select(spaces, 0.45);
    if (usual > 3.15 * unit) return Math.max(standard, Math.min(7 * unit, 1.65 * usual));
  }
  const letters = gaps.filter(gap => gap > 1.9 * unit && gap < standard);
  const words = gaps.filter(gap => gap >= standard && gap < 6 * letter);
  if (letters.length < 3 || words.length < 2) return standard;
  // Some operators vary their letter spaces but leave an unusually long
  // pause between words. Estimate the boundary between those two groups.
  const typicalLetter = select(letters, 0.5);
  const typicalWord = select(words, 0.5);
  if (typicalWord < 2.8 * letter || typicalLetter < 2.45 * unit) return standard;
  return Math.max(standard, (typicalLetter + typicalWord) / 2);
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

function projectCarrier(iq, phaseStep, dt, fine) {
  // Remove the search-bin frequency, then fit the residual rotation. The
  // longer fit needs finer frequency resolution to keep its ends in phase.
  const length = iq.length / 2;
  const baseband = new Float64Array(iq.length);
  const stride = fine ? Math.max(1, Math.min(3, Math.floor(1 / (20 * dt)))) : 1;
  let mass = 0;
  for (let i = 0; i < length; i++) {
    const angle = i * phaseStep;
    const c = Math.cos(angle);
    const s = Math.sin(angle);
    const re = iq[2 * i];
    const im = iq[2 * i + 1];
    baseband[2 * i] = re * c + im * s;
    baseband[2 * i + 1] = im * c - re * s;
    if (i % stride === 0) mass += Math.hypot(re, im);
  }
  const limit = fine ? 10 : 9;
  const resolution = fine ? 0.16 : 1.5;
  let best = ((fine ? 0.45 : 0.51) * mass) ** 2;
  let fit = null;
  for (let hz = -limit; hz <= limit; hz += resolution) {
    const step = 2 * Math.PI * hz * dt;
    const c = Math.cos(stride * step);
    const s = Math.sin(stride * step);
    let x = 1;
    let y = 0;
    let re = 0;
    let im = 0;
    for (let i = 0; i < length; i += stride) {
      re += baseband[2 * i] * x + baseband[2 * i + 1] * y;
      im += baseband[2 * i + 1] * x - baseband[2 * i] * y;
      const next = x * c - y * s;
      y = y * c + x * s;
      x = next;
    }
    const power = re * re + im * im;
    if (power > best) {
      best = power;
      fit = {step, phase: Math.atan2(im, re)};
    }
  }
  if (!fit) return null;
  const amplitude = new Float64Array(length);
  const quadrature = fine ? new Float64Array(length) : null;
  let forward = 0;
  let reverse = 0;
  let side = 0;
  for (let i = 0; i < length; i++) {
    const angle = fit.phase + i * fit.step;
    const re = baseband[2 * i];
    const im = baseband[2 * i + 1];
    const projected = re * Math.cos(angle) + im * Math.sin(angle);
    if (fine) {
      amplitude[i] = projected;
      quadrature[i] = Math.abs(im * Math.cos(angle) - re * Math.sin(angle));
      side += quadrature[i] ** 2;
      if (projected > 0) forward += projected ** 2;
      else reverse += projected ** 2;
    } else {
      amplitude[i] = 0.15 * (re * re + im * im) + 0.85 * Math.max(0, projected) ** 2;
    }
  }
  // A drifting carrier or one which restarts on each mark can have a
  // spectral peak and still point away from the fitted phase during key-down.
  if (fine && (side > 0.46 * forward || reverse > 0.12 * forward)) return null;
  return {values: amplitude, sigma: fine ? select(quadrature, 0.5) / 0.6745 : 0};
}

function variableMarkPeaks(history, {floor, peak}) {
  const range = peak - floor;
  // Count complete weak and strong marks. A word space alone also has
  // low power and should not switch a clean station into fade tracking.
  let crest = 0;
  let weak = 0;
  let strong = 0;
  for (const power of history) {
    const above = power - floor;
    if (above > 0.025 * range) crest = Math.max(crest, above);
    else if (crest) {
      if (crest > 0.7 * range) strong++;
      else if (crest > 0.045 * range && crest < 0.40 * range) weak++;
      crest = 0;
    }
    if (weak >= 2 && strong >= 2) return true;
  }
  return false;
}

function keyingGrid(amplitude, minUnit, maxUnit) {
  // Rising edges recur at even dit counts and falling edges at odd ones.
  // Correlate signed slopes with that cycle. A weak peak leaves the decoder
  // free to follow an irregular sender's individual threshold crossings.
  const edges = [];
  let mass = 0;
  for (let i = 2; i < amplitude.length - 2; i += 2) {
    const slope = amplitude[i + 2] - amplitude[i - 2];
    edges.push(slope);
    mass += Math.abs(slope);
  }
  let best = 0.3 * mass;
  let grid = null;
  for (let cycles = Math.max(4, edges.length / maxUnit); cycles < edges.length / Math.max(2, minUnit); cycles += 0.14) {
    const step = 2 * Math.PI * cycles / edges.length;
    const c = Math.cos(step);
    const s = Math.sin(step);
    let x = 1;
    let y = 0;
    let re = 0;
    let im = 0;
    for (const edge of edges) {
      re += x * edge;
      im += y * edge;
      const next = x * c - y * s;
      y = y * c + x * s;
      x = next;
    }
    const strength = Math.hypot(re, im);
    if (strength > best) {
      best = strength;
      grid = {period: edges.length / cycles, origin: 2 + 2 * Math.atan2(im, re) / step};
    }
  }
  if (!grid) return null;
  const angle = Math.PI / grid.period;
  // One regularly keyed group is insufficient if the sender changes pace.
  const section = Math.ceil(edges.length / 3);
  for (let begin = 0; begin < edges.length; begin += section) {
    const end = Math.min(edges.length, begin + section);
    let re = 0;
    let im = 0;
    let weight = 0;
    for (let i = begin; i < end; i++) {
      const a = angle * (2 + 2 * i - grid.origin);
      re += edges[i] * Math.cos(a);
      im += edges[i] * Math.sin(a);
      weight += Math.abs(edges[i]);
    }
    if (re < 0.12 * weight || Math.abs(im) > 0.52 * re) return null;
  }
  return grid;
}

function clockedMarks(amplitude, threshold, start, {period, origin}) {
  // Each two-dit interval can be silent, contain a dit, or begin a dah.
  // A dah also occupies the first half of the next interval. Compare these
  // possibilities by summing the signed evidence in the middle of each dit.
  const first = Math.floor((start - origin) / (2 * period)) - 2;
  const offset = origin + 2 * first * period;
  const pairs = Math.ceil((amplitude.length - offset) / (2 * period));
  const evidence = new Float64Array(2 * pairs);
  for (let cell = 0; cell < evidence.length; cell++) {
    const begin = offset + cell * period;
    const low = Math.max(0, Math.ceil(begin + 0.15 * period));
    const high = Math.min(amplitude.length, Math.ceil(begin + 0.85 * period));
    for (let i = low; i < high; i++) evidence[cell] += amplitude[i] - threshold;
    if (high > low) evidence[cell] /= high - low;
  }
  const score = new Float64Array(pairs + 2);
  const marks = new Uint8Array(pairs);
  for (let i = pairs - 1; i >= 0; i--) {
    const dit = evidence[2 * i];
    score[i] = score[i + 1] + Math.max(0, dit);
    if (dit > 0) marks[i] = 1;
    if (i + 1 < pairs) {
      const dah = dit + evidence[2 * i + 1] + evidence[2 * i + 2] + score[i + 2];
      if (dah > score[i]) {
        score[i] = dah;
        marks[i] = 3;
      }
    }
  }
  const cells = new Uint8Array(2 * pairs);
  for (let i = 0; i < pairs; i++) {
    cells.fill(1, 2 * i, 2 * i + marks[i]);
    if (marks[i] === 3) i++;
  }
  return i => cells[Math.floor((i - offset) / period)] === 1;
}

function decodeWord(marks, timing) {
  // Mark length and the following silence share a threshold crossing.
  // Their sum gives a second timing measurement between successive onsets.
  const costs = marks.map(({length, gap}) => [timing.dot, timing.dash].map(mark => {
    const gapCost = space => durationCost(gap, space) +
      (timing.onsetWeight || 0) * durationCost(length + gap, mark + space);
    return {mark: durationCost(length, mark), element: gapCost(timing.element), letter: gapCost(timing.letter)};
  }));
  const paths = [{cost: 0, text: ''}];
  for (let i = 0; i < marks.length; i++) {
    for (const [pattern, char] of patterns) {
      const end = i + pattern.length;
      if (end > marks.length) continue;
      let cost = paths[i].cost;
      for (let j = i; j < end; j++) {
        const choice = costs[j][pattern[j - i] === '.' ? 0 : 1];
        cost += choice.mark;
        if (j < marks.length - 1) cost += j === end - 1 ? choice.letter : choice.element;
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
    if (i + 1 < marks.length && marks[i].gap <= timing.word) continue;
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
    this.tunedAt = 0;
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

  hasFilteredNoise(levels, index) {
    // A narrow receiver filter leaves quiet bins at its skirts. A noise
    // estimate taken across the entire search band can then admit key-up hiss.
    const hz = this.tones[index].hz;
    const floors = levels.filter((_, i) => Math.abs(this.tones[i].hz - hz) >= 2.5 * this.lobeWidth)
      .map(level => level.floor);
    return floors.length >= 5 && select(floors, 0.70) > 4 * Math.max(1e-13, select(floors, 0.15));
  }

  flankIndices(index) {
    const result = [];
    for (let i = 0; i < this.tones.length; i++) {
      const distance = Math.abs(this.tones[i].hz - this.tones[index].hz) / this.lobeWidth;
      if (distance >= 2.3 && distance <= 6) result.push(i);
    }
    return result;
  }

  transmittedTogether(candidate, before, background) {
    // A third station can become the loudest signal in every word space.
    // Look for both carriers keyed at once before the apparent handoff.
    if (before <= 0) return false;
    const previous = this.tones[this.selected];
    const other = this.tones[candidate];
    const quietBins = (index, excludeHz) => this.flankIndices(index)
      .filter(i => Math.abs(this.tones[i].hz - excludeHz) > 2 * this.lobeWidth);
    const oldFlanks = quietBins(this.selected, other.hz);
    const newFlanks = quietBins(candidate, previous.hz);
    if (oldFlanks.length < 2 || newFlanks.length < 2) return false;
    const oldPowers = new Float64Array(oldFlanks.length);
    const newPowers = new Float64Array(newFlanks.length);
    const keyedLevel = 0.42 * select(previous.history.slice(0, before), 0.84);
    let keyed = 0;
    let overlap = 0;
    for (let i = 0; i < before; i += 3) {
      if (previous.history[i] < keyedLevel ||
          previous.history[i] < 6 * Math.max(background, this.flankNoise(oldFlanks, i, oldPowers))) continue;
      keyed++;
      if (other.history[i] > 7 * Math.max(background, this.flankNoise(newFlanks, i, newPowers))) overlap++;
    }
    return overlap >= Math.max(4, 0.20 * keyed);
  }

  findReply(background) {
    // Bursts of receiver noise can keep the old channel "busy"
    // throughout a reply. Check for a recent narrow peak on the new pitch.
    const frames = this.lookaheadFrames + this.updateFrames + Math.round(0.16 / this.dt);
    const recent = this.tones.map(tone => {
      const powers = tone.history.slice(-frames);
      return {low: select(powers, 0.20), high: select(powers, 0.89)};
    });
    const prominence = index => {
      const sides = this.flankIndices(index).map(i => recent[i].high);
      return sides.length >= 2 ? recent[index].high / Math.max(background, select(sides, 0.5)) : null;
    };
    const present = prominence(this.selected);
    if (present === null || present >= 2.3) return {lost: false, reply: null};
    let best = 0;
    for (let i = 1; i < this.bandSize; i++) {
      if (recent[i].high - recent[i].low > recent[best].high - recent[best].low) best = i;
    }
    const candidate = recent[best];
    const separated = Math.abs(this.tones[best].hz - this.tones[this.selected].hz) > 2.5 * this.lobeWidth;
    const keyed = candidate.high > 4 * candidate.low && candidate.high > 2.7 * recent[this.selected].high;
    if (!separated || !keyed || prominence(best) <= 7) return {lost: true, reply: null};
    const before = this.tones[best].history.length - frames;
    if (this.transmittedTogether(best, before, background)) return {lost: true, reply: null, interfering: best};
    return {lost: true, reply: best};
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
    const previous = this.selected;
    const current = previous === null ? null : levels[previous];
    const filtered = this.hasFilteredNoise(levels, previous ?? best);
    const {lost, reply, interfering} = filtered && current ? this.findReply(background) : {lost: false, reply: null};
    const hasReply = reply !== null && inBand(reply);
    if (hasReply) best = reply;
    const shouldSwitch = !current || (score(levels[best]) > 2.5 * score(current) &&
      !this.state && this.run > (this.unit || this.maxUnit) * 8);
    const competing = interfering !== undefined && Math.abs(this.tones[interfering].hz - this.tones[best].hz) < 2 * this.lobeWidth;
    if (hasReply || (shouldSwitch && !competing && score(levels[best]) > minCarrierScore && inBand(best))) {
      if (this.selected !== null && Math.abs(this.selected - best) > 2) {
        this.tunedAt = this.frame;
        if (this.state) this.storeMark(this.run - this.pending, this.keyClock - this.pending, false);
        this.commitWord();
        this.state = false;
        this.run = 0;
        this.markPeak = 0;
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
      const withinBand = inBand(this.selected) && !(lost && this.selected === previous);
      this.processKeying(levels, background, score(levels[this.selected]), withinBand, startFrame, endFrame, filtered);
      this.cursor = endFrame;
    }
    if (length > this.historyFrames) {
      const trim = length - this.historyFrames;
      for (const tone of this.tones) tone.history.splice(0, trim);
    }
  }

  carrierCoherence(startFrame, tone) {
    const length = this.frame - startFrame;
    const iq = new Float64Array(2 * length);
    for (let i = 0; i < length; i++) this.tonePower(startFrame + i, tone.coeff, this.window, iq, 2 * i);
    let coherence = 0;
    for (const seconds of [0.055, 0.090, 0.135]) {
      // Non-overlapping windows keep shared noise samples from imitating a
      // carrier. A steady frequency offset rotates all products by one angle.
      const lag = Math.max(Math.ceil(this.window.length / this.hop), Math.round(seconds / this.dt));
      let real = 0;
      let imag = 0;
      let magnitude = 0;
      for (let i = lag; i < length; i += 2) {
        const a = 2 * i;
        const b = 2 * (i - lag);
        const re = iq[a] * iq[b] + iq[a + 1] * iq[b + 1];
        const im = iq[a + 1] * iq[b] - iq[a] * iq[b + 1];
        real += re;
        imag += im;
        magnitude += Math.hypot(re, im);
      }
      coherence += Math.hypot(real, imag) / Math.max(1e-15, magnitude);
    }
    return coherence / 3;
  }

  flankNoise(indices, frame, scratch) {
    for (let k = 0; k < indices.length; k++) scratch[k] = this.tones[indices[k]].history[frame];
    return select(scratch, 0.5);
  }

  coherentKeying(tone, startFrame, start, length, followFade) {
    const from = Math.max(0, length - Math.round(3.2 / this.dt), this.tunedAt - startFrame);
    if (from > start) return null;
    const iq = new Float64Array(2 * (length - from));
    const window = this.unit && this.unit * this.hop < 0.8 * this.window.length ? this.shortWindow : this.window;
    for (let i = from; i < length; i++) this.tonePower(startFrame + i, tone.coeff, window, iq, 2 * (i - from));
    const phase = projectCarrier(iq, 2 * Math.PI * tone.hz * this.dt, this.dt, true);
    if (!phase) return null;
    const {values, sigma} = phase;
    const radius = Math.min(6, Math.round((this.unit || 0.05 / this.dt) * 0.12));
    const amplitude = new Float64Array(values.length);
    let sum = 0;
    for (let j = 0; j < values.length + radius; j++) {
      if (j < values.length) sum += values[j];
      if (j > 2 * radius) sum -= values[j - 2 * radius - 1];
      if (j >= radius) {
        const count = Math.min(values.length - 1, j) - Math.max(0, j - 2 * radius) + 1;
        amplitude[j - radius] = sum / count;
      }
    }
    const samples = amplitude.slice();
    const peak = select(samples, 0.84);
    const threshold = Math.max(1.2 * sigma, 0.5 * peak);
    if (threshold <= 0 || select(samples, 0.20) >= 0.85 * threshold) return null;
    const on = 1.04 * Math.sqrt(this.onGain / 4);
    const off = 0.94 * Math.sqrt(this.offGain / 2.8);
    if (followFade) {
      // Use the residual quadrature noise to set a lower limit in the fade.
      // A two-sided peak follows gain changes through the available lookahead.
      const limits = new Float64Array(amplitude.length);
      const decay = Math.exp(-this.dt / 0.085);
      let crest = 0;
      for (let i = 0; i < limits.length; i++) limits[i] = crest = Math.max(amplitude[i], crest * decay);
      crest = 0;
      for (let i = limits.length - 1; i >= 0; i--) {
        crest = Math.max(amplitude[i], crest * decay);
        limits[i] = Math.max(1.6 * sigma, 0.48 * Math.max(crest, limits[i]), 0.06 * threshold);
      }
      return i => amplitude[i - from] > limits[i - from] * (this.state ? off : on);
    }
    const grid = keyingGrid(amplitude, this.minUnit, this.maxUnit);
    if (!grid || (this.unit && this.runs.length > 16 && Math.abs(Math.log(grid.period / this.unit)) > 0.32)) return null;
    const marks = clockedMarks(amplitude, threshold * Math.sqrt(on * off), start - from, grid);
    return i => marks(i - from);
  }

  processKeying(levels, background, carrierScore, withinBand, startFrame, endFrame, filtered) {
    let {floor, peak} = levels[this.selected];
    const tone = this.tones[this.selected];
    const strong = carrierScore > minCarrierScore && withinBand && (!filtered || carrierScore >= 24 ||
      this.carrierCoherence(Math.max(startFrame, this.frame - this.acquisitionFrames), tone) > 0.38);
    this.filtered = filtered;
    this.active = strong;
    this.signalDb = 10 * Math.log10(1 + carrierScore);
    const length = this.frame - startFrame;
    const start = Math.max(0, this.cursor - startFrame);
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
    this.isolatedReceiver = filtered && isolated;
    // A short window preserves fast elements. A long one trades time
    // resolution for more rejection of noise near a weak carrier.
    const fast = (this.unit || this.minUnit) * this.hop < 0.90 * this.window.length;
    // A reply can have a different level from the previous station.
    // During acquisition or a gain change use the shorter, locally calibrated window.
    const recentPeak = filtered && !fast && carrierScore < 250
      ? select(tone.history.slice(-this.acquisitionFrames), 0.86) : peak;
    const varyingGain = recentPeak < 0.63 * peak || recentPeak > 1.6 * peak;
    const acquiring = this.frame - this.tunedAt < this.historyFrames;
    const shortReceiverWindow = filtered && carrierScore > 35 && (carrierScore > 250 || fast || acquiring || varyingGain);
    const window = (carrierScore > 150 && isolated) || shortReceiverWindow
      ? this.shortWindow : carrierScore < 10 ? this.longWindow : null;
    const coherent = !filtered && (carrierScore < 35 || isolated && carrierScore < 150) && withinBand;
    let fadePhase = null;
    let phaseStart = 0;
    const checkPhase = filtered && isolated && strong && carrierScore > 220;
    if (window || coherent || checkPhase) {
      const from = Math.max(0, Math.min(start - Math.ceil(0.45 / this.dt), length - this.acquisitionFrames));
      const measured = new Float64Array(length);
      const iq = coherent || checkPhase ? new Float64Array(2 * (length - from)) : null;
      const filter = window || this.window;
      for (let i = from; i < length; i++) {
        measured[i] = this.tonePower(startFrame + i, tone.coeff, filter, iq, 2 * (i - from));
      }
      if (checkPhase) {
        fadePhase = projectCarrier(iq, 2 * Math.PI * tone.hz * this.dt, this.dt, true);
        phaseStart = from;
      }
      const projected = coherent && projectCarrier(iq, 2 * Math.PI * tone.hz * this.dt, this.dt, false)?.values;
      if (window || projected) {
        if (projected) measured.set(projected, from);
        history = measured;
        const powers = history.slice(from);
        floor = select(powers, 0.20);
        peak = select(powers, 0.86);
        noiseBackground *= filter.length / this.window.length * (projected ? 1.9 : 1);
      }
    }
    const flanks = filtered ? this.flankIndices(this.selected) : [];
    const flankPowers = new Float64Array(flanks.length);
    if (filtered) {
      // A returning station can be much stronger than the noise-only history
      // at its pitch. Re-estimate the key level over the last acquisition window.
      const recent = history.slice(Math.max(0, length - this.acquisitionFrames));
      peak = Math.max(0.65 * peak, select(recent, 0.90));
      if (flanks.length >= 3) {
        // When the whole receiver output falls, its noise falls with it.
        // A stale absolute threshold would erase the quieter station's dits.
        const noiseLevels = [];
        for (let j = 0; j < length; j += 5) noiseLevels.push(this.flankNoise(flanks, j, flankPowers));
        const recentNoise = select(noiseLevels.slice(-Math.ceil(0.38 / (5 * this.dt))), 0.55);
        const usualNoise = select(noiseLevels, 0.70);
        if (usualNoise > 1e-13 && recentNoise < 0.65 * usualNoise) {
          const gain = Math.max(0.05, recentNoise / usualNoise);
          const local = history.slice(Math.max(0, length - Math.round(0.48 / this.dt)));
          peak = Math.min(peak, Math.max(peak * gain, select(local, 0.85)));
          floor *= gain;
          noiseBackground *= gain;
        }
      }
    }
    const range = Math.max(0, peak - floor);
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
    const checkFades = filtered && strong && carrierScore > 220;
    const regular = checkFades && regularKeying(this.runs.slice(-48), this.unit);
    const probes = this.tones.filter((tone, index) => {
      const distance = Math.abs(tone.hz - this.tones[this.selected].hz);
      return distance >= 2.1 * this.lobeWidth && distance <= 220 &&
        levels[index].peak < 14 * (background + levels[index].floor);
    });
    const adaptToFade = isolated && carrierScore > 55;
    const noiseScale = window ? window.length / this.window.length : 1;
    const focusScale = ((window || this.window).length / this.longWindow.length) ** 2;
    const grid = filtered && isolated && strong && !checkFades && flanks.length >= 3 && this.unit && startFrame >= this.tunedAt
      ? fadedKeyingGrid(tone.history, levels[this.selected], this.runs, this.unit) : null;
    const fading = !filtered && withinBand && carrierScore >= 50 && isolated && variableMarkPeaks(tone.history, levels[this.selected]);
    const coherentMarks = !filtered && withinBand && carrierScore > 2.8 && (carrierScore < 16 || fading)
      ? this.coherentKeying(tone, startFrame, start, length, fading) : null;
    if (coherentMarks) this.active = true;
    let previousCell;
    let focusedMark = false;
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
      let keyThreshold = relative * (this.state ? 0.075 : 0.14);
      if (filtered) {
        // Receiver gain can rise sharply inside a word space. Compare the
        // mark with simultaneous noise around its pitch and with keyed power.
        keyThreshold = Math.max(keyThreshold, Math.max(0.5 * range, localContrast) * (this.state ? 0.21 : 0.29));
        if (flanks.length >= 3) {
          const sideNoise = noiseScale * this.flankNoise(flanks, i, flankPowers);
          let multiple = 5;
          if (envelope[i] > floor + Math.max(gain * noise, keyThreshold, 5 * sideNoise) &&
              envelope[i] <= floor + 30 * sideNoise) {
            // Broadband noise loses more power than a keyed tone in a
            // narrower filter. Check ambiguous frames at both bandwidths.
            const focused = this.tonePower(startFrame + i, tone.coeff, this.longWindow);
            const ratio = focusScale * focused / Math.max(1e-13, history[i]);
            multiple += 25 * Math.max(0, 1 - ratio / 0.70);
          }
          // A selective fade can erase just the middle dit of S. Require a
          // narrow spectral peak at a plausible keying time before lowering
          // the gate. Irregular senders need stronger spectral confirmation.
          if (checkFades && this.timing && localPeak[i] < 0.64 * range && envelope[i] > 5 * sideNoise &&
              envelope[i] <= floor + keyThreshold) {
            const gap = this.keyClock - this.markEnd;
            const element = gap > 0.40 * this.unit && gap < 1.85 * this.unit;
            const letter = Math.abs(gap - this.timing.letter) < 0.60 * this.unit;
            if (this.state || element || letter) {
              const narrow = focusScale * this.tonePower(startFrame + i, tone.coeff, this.longWindow);
              if (regular && narrow > 0.5 * history[i]) keyThreshold *= 0.20;
              else if (narrow > 0.83 * history[i] && envelope[i] > 9 * sideNoise) keyThreshold *= 0.32;
            }
          }
          keyThreshold = Math.max(keyThreshold, multiple * sideNoise);
        }
      }
      let gate = floor + Math.max(gain * noise, keyThreshold);
      // Recover a faded mark when energy along the carrier phase exceeds
      // the measured quadrature noise, even if its absolute power is low.
      if (fadePhase && localPeak[i] < 0.48 * range && fadePhase.values[i - phaseStart] > 3 * fadePhase.sigma) {
        gate = floor + Math.max(0.55 * gain * noise, 0.45 * keyThreshold);
      }
      if (grid) {
        const cell = Math.floor((i - grid.origin) / grid.period);
        if (cell !== previousCell) {
          previousCell = cell;
          focusedMark = false;
          const center = Math.round(grid.origin + (cell + 0.5) * grid.period);
          if (center >= 0 && center < length) {
            // Measure once in the middle of a dit, away from the keying
            // edges. Require energy above both the noise floor and the
            // simultaneous off-frequency noise before restoring the mark.
            const focused = focusScale * this.tonePower(startFrame + center, tone.coeff, this.longWindow);
            const side = noiseScale * this.flankNoise(flanks, center, flankPowers);
            focusedMark = focused > Math.max(0.08 * range, floor + this.onGain * (noise + side));
          }
        }
      }
      const on = coherentMarks ? coherentMarks(i) : (this.state || strong) && (envelope[i] > gate || focusedMark);
      this.keyFrame(on,
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
      // The first few marks can fit two different sending speeds. Keep
      // them in the preview until later onsets settle the word boundary.
      if ((this.runs.length >= 24 && this.timing?.ready && gap > this.timing.word) || this.marks.length >= 120) this.commitWord();
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
    this.unit = bestUnit(this.runs, this.unitGrid, this.unit, this.clockUnit, this.isolatedReceiver);
    if (this.unit) {
      this.timing = estimateTiming(this.runs.slice(-48), this.unit, this.signalDb);
      this.timing.word = this.filtered ? wordBoundary(this.runs, this.unit, this.timing.letter) : 1.57 * this.timing.letter;
    }
  }

  commitWord() {
    if (!this.marks.length) return;
    this.updateTiming();
    const unit = this.unit || this.marks[0].length;
    const timing = this.timing || {dot: unit, dash: 3 * unit, element: unit, letter: 3 * unit, word: 4.71 * unit};
    const words = decodeWords(this.marks, timing);
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
