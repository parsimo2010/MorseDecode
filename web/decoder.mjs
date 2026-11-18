const MORSE = Object.fromEntries([
  ...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('').map((letter, i) =>
    ['.- -... -.-. -.. . ..-. --. .... .. .--- -.- .-.. -- -. --- .--. --.- .-. ... - ..- ...- .-- -..- -.-- --..'.split(' ')[i], letter]),
  ...'0123456789'.split('').map((digit, i) =>
    ['----- .---- ..--- ...-- ....- ..... -.... --... ---.. ----.'.split(' ')[i], digit]),
  ['.-.-.-', '.'], ['--..--', ','], ['..--..', '?'], ['-..-.', '/'],
  ['-....-', '-'], ['-...-', '='], ['.--.-.', '@'], ['.-.-.', '<AR>'],
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
  constructor(sampleRate, {low = 400, high = 1000, minWpm = 5, maxWpm = 50} = {}) {
    if (!(low >= 100 && high > low && high <= 3000 && high < sampleRate / 2 &&
        minWpm >= 5 && maxWpm <= 60 && minWpm < maxWpm)) {
      throw new RangeError('Choose a 100–3000 Hz passband and a valid WPM range.');
    }
    this.sampleRate = sampleRate;
    this.hop = Math.round(sampleRate * 0.005);
    this.dt = this.hop / sampleRate;
    this.minUnit = 1.2 / maxWpm / this.dt;
    this.maxUnit = 1.2 / minWpm / this.dt;
    // A 50 ms Hann window gives weak carriers more separation from noise.
    const windowLength = Math.round(sampleRate * 0.05);
    this.window = Float64Array.from({length: windowLength},
      (_, i) => 0.5 - 0.5 * Math.cos(2 * Math.PI * i / (windowLength - 1)));
    this.audio = new Float64Array(this.window.length);
    this.windowed = new Float64Array(this.window.length);
    this.fill = 0;
    const bins = Math.ceil((high - low) / 12);
    this.tones = Array.from({length: bins + 1}, (_, i) => {
      const hz = low + i * (high - low) / bins;
      return {hz, coeff: 2 * Math.cos(2 * Math.PI * hz / sampleRate), history: []};
    });
    this.frame = 0;
    this.cursor = 0;
    this.selected = null;
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
      this.audio.set(samples.subarray(offset, offset + n), this.fill);
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
    if (this.frame % 32 === 0) this.processFrames();
  }

  processFrames(final = false) {
    const length = this.tones[0].history.length;
    if (length < (final ? 20 : 256)) return;

    const levels = this.tones.map(tone => {
      const sorted = [...tone.history].sort((a, b) => a - b);
      return {floor: quantile(sorted, 0.20), peak: quantile(sorted, 0.86)};
    });
    const typical = levels.map(level => level.floor).sort((a, b) => a - b);
    const background = Math.max(1e-13, quantile(typical, 0.45));
    const score = ({floor, peak}) => (peak - floor) / (floor + 2 * background);
    let best = 0;
    for (let i = 1; i < levels.length; i++) {
      if (score(levels[i]) > score(levels[best])) best = i;
    }
    const current = this.selected === null ? null : levels[this.selected];
    const shouldSwitch = !current || (score(levels[best]) > 2.5 * score(current) &&
      !this.state && this.run > (this.unit || this.maxUnit) * 8);
    const carrierThreshold = 5;
    if (shouldSwitch && score(levels[best]) > carrierThreshold) {
      if (this.selected !== null && Math.abs(this.selected - best) > 2) {
        this.commitWord();
        this.unit = null;
        this.runs = [];
        this.pending = 0;
      }
      this.selected = best;
    }
    const startFrame = this.frame - length;
    const endFrame = this.frame - (final ? 0 : 28);
    if (this.selected !== null) {
      const {floor, peak} = levels[this.selected];
      const contrast = peak - floor;
      const strong = score(levels[this.selected]) > carrierThreshold;
      // An absolute noise gate prevents threshold collapse during idle periods.
      const on = floor + Math.max(4 * (background + floor), contrast * 0.14);
      const off = floor + Math.max(2.8 * (background + floor), contrast * 0.075);
      const history = this.tones[this.selected].history;
      for (let i = Math.max(0, this.cursor - startFrame); i < endFrame - startFrame; i++) {
        const power = (history[Math.max(0, i - 1)] + 2 * history[i] + history[Math.min(length - 1, i + 1)]) / 4;
        this.keyFrame((this.state || strong) && power > (this.state ? off : on));
      }
    }
    if (this.selected !== null) this.cursor = endFrame;
    if (length > 768) {
      const trim = length - 768;
      for (const tone of this.tones) tone.history.splice(0, trim);
    }
  }

  keyFrame(on) {
    this.run++;
    if (on === this.state) {
      this.pending = 0;
    } else {
      this.pending++;
      const debounce = this.state ? Math.max(2, Math.round((this.unit || this.minUnit) * 0.37)) : 2;
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
    this.text += (this.wordSeen ? ' ' : '') + decodeWord(this.marks, unit);
    this.wordSeen = true;
    this.marks = [];
  }

  snapshot() {
    const preview = this.unit && this.marks.length ? decodeWord(this.marks, this.unit) : '';
    return {
      text: this.text,
      preview: this.text && preview ? ' ' + preview : preview,
      frequency: this.selected === null ? null : this.tones[this.selected].hz,
      wpm: this.unit ? 1.2 / (this.dt * this.unit) : null
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
