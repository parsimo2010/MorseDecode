import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
import {CWDecoder, MORSE} from '../morse_decode/core/decoder.mjs';

const codes = new Map(Object.entries(MORSE).map(([code, text]) => [text, code]));

function random(seed) {
  return () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return (seed + 0.5) / 2 ** 32;
  };
}

function keying(text, {wpm, jitter = 0, dah = 3, element = 1, letter = 3, word = 7, swing = 0}, rng) {
  const dit = 1.2 / wpm;
  const runs = [];
  let time = 0.25;
  const add = (units, on) => {
    const pace = 1 + swing * Math.sin(2 * Math.PI * time / 3.1);
    const end = time + dit * units * pace * (1 + jitter * (2 * rng() - 1));
    if (on) runs.push([time, end]);
    time = end;
  };
  text.split(' ').forEach((token, w) => {
    if (w) add(word, false);
    Array.from(token.matchAll(/<[^>]+>|./g), match => match[0]).forEach((char, i) => {
      if (i) add(letter, false);
      Array.from(codes.get(char)).forEach((mark, j) => {
        if (j) add(element, false);
        add(mark === '.' ? 1 : dah, true);
      });
    });
  });
  return [runs, time + 0.9];
}

function synth(text, options, seed) {
  const {rate = 8000, hz = 670, wpm = 23, drift = 0, fade = 0, fadeHz = 0.8, noiseDb = Infinity,
    bandwidth = rate / 2, blocker = 0, qrm = 0, qrn = 0, quiet = false,
    phaseResets = false, aliasInterferer = false, ...timing} = options;
  const rng = random(seed);
  const noiseRng = random(seed ^ 0x2ec15);
  const [marks, duration] = keying(text, {wpm, ...timing}, rng);
  const [interferer] = keying('TEST 5NN EU DX CQ K4TQ TEST K4TQ QRZ PSE AGN', {wpm: 28, jitter: 0.08}, rng);
  const makeEnvelope = runs => {
    let index = 0;
    return t => {
      while (index < runs.length && t >= runs[index][1]) index++;
      if (index === runs.length || t < runs[index][0]) return 0;
      return Math.min(1, (t - runs[index][0]) / 0.003, (runs[index][1] - t) / 0.003);
    };
  };
  const signal = makeEnvelope(marks);
  const other = makeEnvelope(interferer);
  const offsets = phaseResets ? marks.map(() => 2 * Math.PI * rng()) : [];
  let phaseIndex = 0;
  const samples = new Float32Array(Math.round(rate * duration));
  const noiseRms = Math.SQRT1_2 * 10 ** (-noiseDb / 20);
  // Gaussian quadrature noise with a one-pole low-pass centered on the carrier.
  const a = -Math.expm1(-Math.PI * bandwidth / rate);
  const normalization = Math.sqrt((2 - a) / a);
  let iNoise = 0;
  let qNoise = 0;
  let staticLevel = 0;
  for (let i = 0; i < samples.length; i++) {
    const t = i / rate;
    const phase = 2 * Math.PI * (hz * t + drift * t * t / (2 * duration));
    while (phaseResets && phaseIndex + 1 < marks.length && t >= marks[phaseIndex + 1][0]) phaseIndex++;
    const noiseAngle = 2 * Math.PI * noiseRng();
    const radius = Math.sqrt(-2 * Math.log(noiseRng()));
    const normal = radius * Math.cos(noiseAngle);
    let noise = normal;
    if (bandwidth < rate / 2) {
      iNoise += a * (normal - iNoise);
      qNoise += a * (radius * Math.sin(noiseAngle) - qNoise);
      noise = normalization * (iNoise * Math.cos(phase) + qNoise * Math.sin(phase));
    }
    if (qrn && noiseRng() < 1.1 / rate) staticLevel = qrn;
    staticLevel *= 1 - 1 / (0.018 * rate);
    const gain = 1 - fade * (0.5 + 0.5 * Math.sin(2 * Math.PI * fadeHz * t + seed)) ** 3;
    samples[i] = (quiet ? 0 : signal(t) * gain * Math.sin(phase + (offsets[phaseIndex] || 0))) + (noiseRms + staticLevel) * noise
      + blocker * Math.sin(2 * Math.PI * (hz + 44) * t)
      + qrm * other(t) * Math.sin(2 * Math.PI * (hz + 65) * t)
      + (aliasInterferer ? 8 * other(t) * Math.sin(2 * Math.PI * (4000 - hz) * t) : 0);
  }
  return {samples, rate, reference: quiet ? '' : text};
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

function receiverExchange(text, {idle = false, competing = false}, seed) {
  const rate = 8000;
  const words = text.split(' ');
  const split = Math.ceil(words.length / 2);
  const turns = [words.slice(0, split).join(' '), words.slice(split).join(' '), 'R TNX'];
  const audio = turns.map((turn, i) => synth(turn, {
    hz: i === 1 ? 617 : 752, wpm: i === 1 ? 26 : 19, jitter: 0.07,
    letter: i === 1 ? 3 : 3.7, word: i === 1 ? 7 : 8.6
  }, seed + i).samples);
  const samples = new Float32Array(audio.reduce((sum, turn) => sum + turn.length, 0));
  const other = competing ? synth('TEST K7RV 5NN TU CQ JA DE JA3AB K', {hz: 847, wpm: 26}, 1234).samples : null;
  const rng = random(seed ^ 0x39fa);
  let offset = 0;
  let envelope = 0;
  let real = 0;
  let imag = 0;
  let smoothReal = 0;
  let smoothImag = 0;
  const pole = -Math.expm1(-2 * Math.PI * 130 / rate);
  const release = Math.exp(-1 / (0.085 * rate));
  for (const [k, turn] of audio.entries()) {
    for (const value of turn) {
      // Two low-pass poles in quadrature form a fixed receiver passband.
      real += pole * (rng() - 0.5 - real);
      imag += pole * (rng() - 0.5 - imag);
      smoothReal += pole * (real - smoothReal);
      smoothImag += pole * (imag - smoothImag);
      const angle = 2 * Math.PI * 694 * offset / rate;
      const noise = 1.15 * (smoothReal * Math.cos(angle) + smoothImag * Math.sin(angle));
      const interference = other ? 0.20 * other[(offset + 191) % other.length] : 0;
      const input = (idle ? 0 : value * (k === 1 ? 0.27 : 0.84)) + noise + interference;
      envelope = Math.max(Math.abs(input), envelope * release);
      samples[offset++] = input / Math.max(0.13, envelope);
    }
  }
  return {samples, rate, reference: idle ? '' : turns.join(' ')};
}

const cases = [
  ['Clean', {}],
  ['Clean, high speed', {wpm: 46, hz: 945}],
  ['30 dB in 500 Hz noise', {noiseDb: 30, bandwidth: 500}],
  ['15 dB in 500 Hz noise', {noiseDb: 15, bandwidth: 500}],
  ['15 dB with QSB and variable keying', {noiseDb: 15, bandwidth: 500, fade: 0.94, jitter: 0.19}],
  ['0 dB in 500 Hz noise', {noiseDb: 0, bandwidth: 500, wpm: 19}],
  ['−6 dB in 500 Hz noise', {noiseDb: -6, bandwidth: 500, wpm: 17}],
  ['−12 dB white noise', {noiseDb: -12, wpm: 22}],
  ['−15 dB white noise', {noiseDb: -15, wpm: 18}],
  ['Fast CW in white noise', {noiseDb: -10, wpm: 38, hz: 732}],
  ['Carrier restarts each mark', {noiseDb: -9, phaseResets: true}],
  ['48 kHz with strong out-of-band CW', {rate: 48000, aliasInterferer: true}],
  ['Deep QSB', {fade: 0.94, fadeHz: 0.39, noiseDb: 2}],
  ['Near steady tone', {blocker: 1.55, noiseDb: -2}],
  ['Near keyed station', {qrm: 0.8, noiseDb: -3}],
  ['Carrier drift', {drift: 84, noiseDb: -5}],
  ['QRN crashes', {qrn: 7, noiseDb: -5}],
  ['Straight key', {jitter: 0.27, swing: 0.16, dah: 2.55, element: 1.29, letter: 3.7}],
  ['Bug', {jitter: 0.20, swing: 0.13, dah: 4, element: 0.86, letter: 2.7}],
  ['Farnsworth', {wpm: 25, letter: 6.2, word: 13.7}],
  ['Idle noise and steady tone', {quiet: true, noiseDb: -4, qrn: 4, blocker: 2}],
  ['Receiver filter, AGC and station replies', {}, receiverExchange, 0.20],
  ['Receiver with a competing keyed station', {competing: true}, receiverExchange, 0.15],
  ['Receiver filter and idle AGC noise', {idle: true}, receiverExchange, 0]
];

const messages = [
  'CQ NA DE K5LZ K5LZ PSE K', 'GM UR RST 579 IN AZ NAME JO <AR>',
  'THE EAST WIND HAS LOWERED THE TEMPERATURE', 'Q8NZ 42V6 T9X5 7JPR 022',
  'VVV DE GB3RS LOC IO91 RU QSL', 'UR RIG SOUNDS GREAT TOM HW CPY <KN>',
  'BRING THE SMALL BATTERY ON FRIDAY', 'M9R2 VK8/ZZ 8FX1 73QK 606'
];

const args = process.argv.slice(2);
const flag = name => args.find(arg => arg.startsWith(`--${name}=`))?.split('=').slice(1).join('=');
const candidate = flag('candidate') ? await import(pathToFileURL(flag('candidate'))) : null;
const versions = [[flag('candidate') || 'current', candidate?.CWDecoder || CWDecoder]];
if (flag('baseline')) {
  const source = execFileSync('git', ['show', `${flag('baseline')}:morse_decode/core/decoder.mjs`]);
  const baseline = await import(`data:text/javascript;base64,${source.toString('base64')}`);
  versions.unshift([flag('baseline'), baseline.CWDecoder]);
}

function measure(Decoder, {samples, rate, reference}) {
  const decoder = new Decoder(rate);
  const block = Math.round(rate * 0.020);
  const started = performance.now();
  for (let i = 0; i < samples.length; i += block) {
    decoder.push(samples.subarray(i, i + block));
    if (i % (block * 6) === 0) decoder.snapshot();
  }
  const {text, frequency, wpm} = decoder.finish();
  return {edits: edits(reference, text), ms: performance.now() - started, text, frequency, wpm};
}

const fixture = flag('fixture');
if (fixture) {
  const {rate, pcm, reference} = JSON.parse(readFileSync(fixture, 'utf8'));
  const bytes = Buffer.from(pcm, 'base64');
  const samples = Float32Array.from({length: bytes.length / 2}, (_, i) => bytes.readInt16LE(2 * i) / 32768);
  const results = versions.map(([label, Decoder]) => [label, measure(Decoder, {samples, rate, reference})]);
  if (args.includes('--json')) console.log(JSON.stringify(results));
  else {
    for (const [label, result] of results) {
      console.log(label, `${result.edits}/${reference.length} edits`);
      if (args.includes('--verbose')) console.log(result.text);
    }
  }
} else {
  const holdout = args.includes('--holdout');
  const selected = holdout ? messages.slice(4) : messages.slice(0, 4);
  const totals = versions.map(() => ({edits: 0, chars: 0, ms: 0}));
  for (const [label, options, generate = synth, limit] of cases) {
    if (flag('match') && !label.toLowerCase().includes(flag('match').toLowerCase())) continue;
    const fixtures = selected.map((message, i) => {
      const seed = (holdout ? 7121 : 47) + i * 81;
      return generate(message, options, seed);
    });
    const chars = fixtures.reduce((n, fixture) => n + fixture.reference.length, 0);
    const scores = versions.map(([name, Decoder], v) => {
      let errors = 0;
      for (const fixture of fixtures) {
        const result = measure(Decoder, fixture);
        if (args.includes('--verbose')) {
          console.log(name, fixture.reference, `→ (${result.edits})`, result.text,
            `[${result.frequency ?? '?'} Hz, ${result.wpm?.toFixed(1) ?? '?'} WPM]`);
        }
        errors += result.edits;
        totals[v].ms += result.ms;
      }
      totals[v].edits += errors;
      totals[v].chars += chars;
      if (args.includes('--check') && v === versions.length - 1 && limit !== undefined && errors > limit * chars) {
        throw new Error(`${label}: ${errors} edits exceeds the limit of ${Math.floor(limit * chars)}`);
      }
      return `${errors}/${chars}`;
    });
    console.log(label.padEnd(37), scores.join(' → '));
  }
  for (const [[name], {edits, chars, ms}] of versions.map((version, i) => [version, totals[i]])) {
    const metric = chars ? `${edits}/${chars} edits, ${(100 * edits / chars).toFixed(2)}% CER` : `${edits} insertions`;
    console.log(name, `${metric}, ${(ms / 1000).toFixed(2)} s processing`);
  }
}
