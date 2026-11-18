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

function quantile(sorted, fraction) {
  return sorted[Math.floor((sorted.length - 1) * fraction)];
}

function durationCost(length, expected) {
  const error = Math.abs(Math.log(length / expected));
  return error < 0.35 ? error * error / 0.7 : error - 0.175;
}

function bestUnit(runs, min, max, previous) {
  const usable = runs.filter(({on, length}) => on || length < (previous || max) * 4.8).slice(-48);
  if (usable.filter(run => run.on).length < 3) return previous;
  let best = previous;
  let bestCost = Infinity;
  for (let unit = min; unit <= max * 1.001; unit *= 1.025) {
    let cost = previous ? 0.065 * Math.abs(Math.log(unit / previous)) : 0;
    for (const {on, length} of usable) {
      const fit = Math.min(durationCost(length, unit), durationCost(length, unit * 3));
      // Long silences can be word gaps, including extended spacing.
      cost += Math.min(on ? 0.8 : 0.45, fit) / usable.length;
    }
    if (cost < bestCost) {
      bestCost = cost;
      best = unit;
    }
  }
  return best;
}

const patterns = Object.entries(MORSE);

function decodeWord(marks, unit) {
  const paths = [{cost: 0, text: ''}];
  for (let i = 0; i < marks.length; i++) {
    for (const [pattern, char] of patterns) {
      const end = i + pattern.length;
      if (end > marks.length) continue;
      let cost = paths[i].cost;
      for (let j = i; j < end; j++) {
        const {length, gap} = marks[j];
        cost += durationCost(length, unit * (pattern[j - i] === '.' ? 1 : 3));
        if (j < marks.length - 1) cost += durationCost(gap, unit * (j === end - 1 ? 3 : 1));
      }
      if (!paths[end] || cost < paths[end].cost) paths[end] = {cost, text: paths[i].text + char};
    }
  }
  return paths[marks.length].text;
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
    this.hop = Math.round(sampleRate * hopMs / 1000);
    const windowLength = Math.round(sampleRate * windowMs / 1000);
    if (!(this.hop > 0 && Number.isFinite(windowLength) && windowLength > this.hop &&
        Number.isFinite(debounceMs) && debounceMs >= 0 && Number.isFinite(offDb) &&
        Number.isFinite(onDb) && offDb < onDb)) {
      throw new RangeError('Check the analysis window, hop, debounce, and detection thresholds.');
    }
    this.dt = this.hop / sampleRate;
    this.lobeWidth = sampleRate / windowLength;
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
    // A 50 ms Hann window gives weak carriers more separation from noise.
    this.window = Float64Array.from({length: windowLength},
      (_, i) => 0.5 - 0.5 * Math.cos(2 * Math.PI * i / (windowLength - 1)));
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
    this.tones = frequencies.map(hz => ({hz, coeff: 2 * Math.cos(2 * Math.PI * hz / sampleRate), history: []}));
    this.frame = 0;
    this.cursor = 0;
    this.selected = null;
    this.active = false;
    this.signalDb = null;
    this.callsign = '';
    this.unit = null;
    this.text = '';
    this.runs = [];
    this.marks = [];
    this.state = false;
    this.run = 0;
    this.pending = 0;
    this.wordSeen = false;
  }

  push(samples) {
    for (let offset = 0; offset < samples.length;) {
      const n = Math.min(this.audio.length - this.fill, samples.length - offset);
      if (this.agc) {
        const agc = this.agc;
        for (let i = 0; i < n; i++) {
          const sample = samples[offset + i];
          agc.meanSquare += agc.alpha * (sample ** 2 - agc.meanSquare);
          const gain = Math.min(100, agc.target / Math.max(1e-5, Math.sqrt(agc.meanSquare)));
          this.audio[this.fill + i] = sample * gain;
        }
      } else {
        this.audio.set(samples.subarray(offset, offset + n), this.fill);
      }
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

  processFrames(final = false) {
    const length = this.tones[0].history.length;
    if (length < (final ? this.finalFrames : this.acquisitionFrames)) return;

    const levels = this.tones.map(tone => {
      const sorted = [...tone.history].sort((a, b) => a - b);
      return {floor: quantile(sorted, 0.20), peak: quantile(sorted, 0.86)};
    });
    const typical = levels.slice(0, this.bandSize).map(level => level.floor).sort((a, b) => a - b);
    const background = Math.max(1e-13, quantile(typical, 0.45));
    const score = ({floor, peak}) => (peak - floor) / (floor + 2 * background);
    let best = 0;
    for (let i = 1; i < this.bandSize; i++) {
      if (score(levels[i]) > score(levels[best])) best = i;
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
    const carrierThreshold = 5;
    if (shouldSwitch && score(levels[best]) > carrierThreshold && inBand(best)) {
      if (this.selected !== null && Math.abs(this.selected - best) > 2) {
        this.commitWord();
        this.unit = null;
        this.runs = [];
        this.pending = 0;
      }
      this.selected = best;
    }
    const startFrame = this.frame - length;
    const endFrame = this.frame - (final ? 0 : this.lookaheadFrames);
    if (this.selected !== null) {
      const {floor, peak} = levels[this.selected];
      const contrast = peak - floor;
      const carrierScore = score(levels[this.selected]);
      const strong = carrierScore > carrierThreshold && inBand(this.selected);
      this.active = strong;
      this.signalDb = 10 * Math.log10(1 + carrierScore);
      // An absolute noise gate prevents threshold collapse during idle periods.
      const on = floor + Math.max(this.onGain * (background + floor), contrast * 0.14);
      const off = floor + Math.max(this.offGain * (background + floor), contrast * 0.075);
      const history = this.tones[this.selected].history;
      for (let i = Math.max(0, this.cursor - startFrame); i < endFrame - startFrame; i++) {
        const power = (history[Math.max(0, i - 1)] + 2 * history[i] + history[Math.min(length - 1, i + 1)]) / 4;
        this.keyFrame((this.state || strong) && power > (this.state ? off : on));
      }
    }
    if (this.selected !== null) this.cursor = endFrame;
    if (length > this.historyFrames) {
      const trim = length - this.historyFrames;
      for (const tone of this.tones) tone.history.splice(0, trim);
    }
  }

  keyFrame(on) {
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
          if (length >= Math.max(this.minUnit * 0.65, (this.unit || 0) * 0.40)) {
            this.marks.push({length, gap: 0});
            this.remember(true, length);
          }
        } else if (this.marks.length) {
          this.marks.at(-1).gap = length;
          this.remember(false, length);
          this.unit = bestUnit(this.runs, this.minUnit, this.maxUnit, this.unit);
          if ((this.unit && length > 4.7 * this.unit) || this.marks.length >= 120) this.commitWord();
        }
        this.run = this.pending;
        this.pending = 0;
        this.state = on;
      }
    }
    if (!this.state && !this.pending && this.marks.length &&
        this.run > Math.max(this.maxUnit * 4, (this.unit || 0) * 8)) this.commitWord();
  }

  remember(on, length) {
    this.runs.push({on, length});
    if (this.runs.length > 64) this.runs.shift();
  }

  commitWord() {
    if (!this.marks.length) return;
    this.unit = bestUnit(this.runs, this.minUnit, this.maxUnit, this.unit);
    const unit = this.unit || this.marks[0].length;
    const word = decodeWord(this.marks, unit);
    this.text += (this.wordSeen ? ' ' : '') + word;
    if (/^(?:[A-Z]{1,2}\d[A-Z]{2,3}|[A-Z]{2}\d[A-Z])$/.test(word)) this.callsign = word;
    this.wordSeen = true;
    this.marks = [];
  }

  snapshot() {
    const preview = this.unit && this.marks.length ? decodeWord(this.marks, this.unit) : '';
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
    this.processFrames(true);
    if (this.state) {
      const length = this.run - this.pending;
      if (length >= Math.max(this.minUnit * 0.65, (this.unit || 0) * 0.40)) {
        this.marks.push({length, gap: 0});
        this.remember(true, length);
      }
      this.state = false;
    }
    this.commitWord();
    return this.snapshot();
  }
}

export {CWDecoder, MORSE};
