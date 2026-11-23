import assert from 'node:assert/strict';
import {CWDecoder, MORSE} from '../morse_decode/core/decoder.mjs';

const codes = Object.fromEntries(Object.entries(MORSE).map(([code, char]) => [char, code]));
const messages = [
  'CQ CQ DE W1AW TESTING MORSE CODE 123',
  'THE QUICK BROWN FOX JUMPS OVER 79',
  'K7ABC DE N0XYZ RST 599 TNX FER QSO'
];

function random(seed) {
  return () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return (seed + 0.5) / 4294967296;
  };
}

function synth(text, {
  rate = 8000, wpm = 22, speedChange = 0, hz = 673, snr = Infinity,
  jitter = 0, fade = 0, blocker = 0, seed = 1, silence = false
} = {}) {
  const rng = random(seed);
  const samples = [];
  const noise = Math.SQRT1_2 * 10 ** (-snr / 20);
  let unit = 1.2 / wpm;
  const add = (seconds, keyed) => {
    const length = Math.round(seconds * rate);
    for (let i = 0; i < length; i++) {
      const t = samples.length / rate;
      const envelope = Math.min(1, i / (0.002 * rate), (length - i) / (0.002 * rate));
      const fading = 1 - fade * (0.5 + 0.5 * Math.sin(2 * Math.PI * 0.83 * t + seed)) ** 3;
      const gaussian = Math.sqrt(-2 * Math.log(rng())) * Math.cos(2 * Math.PI * rng());
      samples.push((keyed && !silence ? envelope * fading * Math.sin(2 * Math.PI * hz * t) : 0)
        + noise * gaussian + blocker * Math.sin(2 * Math.PI * 817 * t));
    }
  };
  const run = (n, keyed) => add(unit * n * (1 + jitter * (2 * rng() - 1)), keyed);
  add(0.28, false);
  const words = text.split(' ');
  words.forEach((word, w) => {
    if (w === Math.floor(words.length / 2) && speedChange) unit = 1.2 / speedChange;
    [...word].forEach((char, i) => {
      [...codes[char]].forEach((mark, j) => {
        if (j) run(1, false);
        run(mark === '.' ? 1 : 3, true);
      });
      if (i < word.length - 1) run(3, false);
    });
    if (w < words.length - 1) run(7, false);
  });
  add(1, false);
  return Float32Array.from(samples);
}

function decode(text, options = {}, chunk = 731) {
  const audio = synth(text, options);
  const decoder = new CWDecoder(options.rate || 8000);
  for (let i = 0; i < audio.length; i += chunk) decoder.push(audio.subarray(i, i + chunk));
  return decoder.finish();
}

function edits(a, b) {
  let row = Array.from({length: b.length + 1}, (_, i) => i);
  for (let i = 0; i < a.length; i++) {
    const next = [i + 1];
    for (let j = 0; j < b.length; j++) {
      next.push(Math.min(next[j] + 1, row[j + 1] + 1, row[j] + Number(a[i] !== b[j])));
    }
    row = next;
  }
  return row[b.length];
}

const cases = [
  ['Clean', {}, 0.02],
  ['Slow, fast and passband edges', {wpm: [8, 35, 49], hz: [405, 991, 541]}, 0.06],
  ['48 kHz capture', {rate: 48000, wpm: 27}, 0.03],
  ['Speed change 18 to 28 WPM', {wpm: 18, speedChange: 28}, 0.19],
  ['Jitter ±15%', {jitter: 0.15}, 0.06],
  ['Jitter ±35%', {jitter: 0.35}, 0.20],
  ['White noise −6 dB', {snr: -6}, 0.12],
  ['White noise −12 dB', {snr: -12}, 0.27],
  ['White noise −18 dB', {snr: -18}],
  ['Fade to 35% amplitude', {fade: 0.65}, 0.18],
  ['Fade to 10% amplitude', {fade: 0.9}, 0.05],
  ['Steady interferer +6 dB', {blocker: 2, snr: -3}, 0.13],
  ['Combined noise, jitter and fading', {snr: -8, jitter: 0.18, fade: 0.55}, 0.39]
];
const failures = [];
for (const [label, conditions, limit] of cases) {
  let errors = 0;
  let chars = 0;
  const results = messages.map((message, i) => {
    const options = Object.fromEntries(Object.entries(conditions)
      .map(([key, value]) => [key, Array.isArray(value) ? value[i] : value]));
    const result = decode(message, {...options, seed: i + 101});
    errors += edits(message, result.text);
    chars += message.length;
    return result.text;
  });
  const cer = errors / chars;
  console.log(label.padEnd(36), (100 * cer).toFixed(1).padStart(6) + '% CER', '(' + errors + '/' + chars + ')');
  if (limit !== undefined && cer > limit) failures.push({label, limit, cer, results});
}
assert.deepEqual(failures, []);
assert.equal(decode(messages[0], {silence: true, blocker: 2, snr: -7}).text, '');
const reference = decode(messages[0], {hz: 721, wpm: 26});
assert.equal(reference.text, messages[0]);
assert.ok(Math.abs(reference.frequency - 721) < 15, JSON.stringify(reference));
assert.ok(Math.abs(reference.wpm - 26) < 3, JSON.stringify(reference));
assert.deepEqual(decode(messages[0], {hz: 721, wpm: 26}, 128), reference);
const weak = {hz: 673, wpm: 18, snr: -15, seed: 103};
assert.deepEqual(decode(messages[0], weak, 128), decode(messages[0], weak, 731));

const cut = new CWDecoder(8000);
cut.push(synth(messages[2], {wpm: 40}).subarray(0, -7999));
assert.equal(cut.finish().text, messages[2]);
