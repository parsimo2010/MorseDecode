import {execFileSync, spawn} from 'node:child_process';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {setTimeout as sleep} from 'node:timers/promises';
import {CWDecoder} from '../morse_decode/core/decoder.mjs';

const args = process.argv.slice(2);
const flag = name => args.find(arg => arg.startsWith(`--${name}=`))?.slice(name.length + 3);

function measure(CWDecoder, bands, weak = false) {
  const rate = 48000;
  const block = rate * 0.02;
  const seconds = 23;
  const decoders = bands.map(band => new CWDecoder(rate, band));
  const pattern = '10111000111010100010101110001110111010000000';
  let seed = 372;
  const samples = Float32Array.from({length: rate * seconds}, (_, i) => {
    const t = i / rate;
    const keyed = pattern[Math.floor(t * 19) % pattern.length] === '1';
    const signal = keyed ? Math.sin(2 * Math.PI * 673 * t) : 0;
    if (!weak) return 0.5 * signal + 0.18 * Math.sin(2 * Math.PI * 817 * t);
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return 0.075 * signal + 0.9 * (seed / 2 ** 31 - 1);
  });
  const times = [];
  for (let i = 0; i < samples.length; i += block) {
    const chunk = samples.subarray(i, i + block);
    const start = performance.now();
    for (const decoder of decoders) {
      decoder.push(chunk);
      if (i % (block * 6) === 0) decoder.snapshot();
    }
    times.push(performance.now() - start);
  }
  for (const decoder of decoders) decoder.finish();
  times.sort((a, b) => a - b);
  return {
    load: times.reduce((sum, ms) => sum + ms, 0) / (seconds * 10),
    p95: times[Math.floor(times.length * 0.95)],
    p99: times[Math.floor(times.length * 0.99)]
  };
}

function report(title, {load, p95, p99}) {
  console.log(title, `${load.toFixed(1)}% of real time, p95 ${p95.toFixed(2)} ms, p99 ${p99.toFixed(2)} ms per 20 ms block`);
}

const scenarios = [
  ['default passband', [{}]],
  ['weak CW', [{}], true],
  ['wide passband', [{low: 100, high: 3000}]],
  ['three guarded passbands', [400, 600, 800].map(low => ({low, high: low + 200, guard: true, includeHigh: low === 800}))]
];

const versions = [['Node', CWDecoder]];
if (flag('baseline')) {
  const source = execFileSync('git', ['show', `${flag('baseline')}:morse_decode/core/decoder.mjs`]);
  const reference = await import(`data:text/javascript;base64,${source.toString('base64')}`);
  versions.unshift([flag('baseline'), reference.CWDecoder]);
}
for (const [version, Decoder] of versions) {
  for (const [label, bands, weak] of scenarios) report(`${version}, ${label}`, measure(Decoder, bands, weak));
}

const executable = flag('browser');
if (executable) {
  execFileSync(process.execPath, ['web/build.mjs']);
  const page = await readFile('dist/index.html', 'utf8');
  const worker = JSON.parse(page.match(/^const workerSource = (.+);$/m)[1]);
  const profile = await mkdtemp(join(resolve(tmpdir()), 'morsedecode-chrome-'));
  const browser = spawn(executable, ['--headless', '--no-first-run', '--remote-debugging-port=0',
    `--user-data-dir=${profile}`, 'about:blank'], {stdio: 'ignore', windowsHide: true});
  const exited = new Promise(done => browser.once('close', done));
  let socket;
  try {
    let port;
    for (let attempt = 0; attempt < 100 && !port; attempt++) {
      if (browser.exitCode !== null) throw new Error('Chrome exited before opening DevTools.');
      const active = await readFile(join(profile, 'DevToolsActivePort'), 'utf8').catch(error => {
        if (error.code !== 'ENOENT') throw error;
      });
      if (active) [port] = active.split('\n');
      else await sleep(100);
    }
    if (!port) throw new Error('Chrome did not open a DevTools port.');
    const targets = await fetch(`http://127.0.0.1:${port}/json/list`).then(response => response.json());
    socket = new WebSocket(targets.find(target => target.type === 'page').webSocketDebuggerUrl);
    await new Promise((done, reject) => {
      socket.addEventListener('open', done, {once: true});
      socket.addEventListener('error', reject, {once: true});
    });
    let id = 0;
    const command = (method, params = {}) => new Promise((done, reject) => {
      const request = ++id;
      const listener = ({data}) => {
        const response = JSON.parse(data);
        if (response.id !== request) return;
        socket.removeEventListener('message', listener);
        if (response.error) reject(new Error(response.error.message));
        else done(response.result);
      };
      socket.addEventListener('message', listener);
      socket.send(JSON.stringify({id: request, method, params}));
    });
    const evaluate = async expression => {
      const result = await command('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
      return result.result.value;
    };

    // A dedicated worker uses the decoder from the production HTML bundle.
    // DevTools CPU throttling applies to the page thread. Use the same code
    // there under a sixfold slowdown as a separate low-power stress test.
    for (const [label, bands, weak = false] of scenarios.slice(0, 3)) {
      const run = `(${measure})(CWDecoder, ${JSON.stringify(bands)}, ${weak})`;
      const source = `${worker}\nself.postMessage(${run});`;
      const direct = await evaluate(`new Promise((done, reject) => {
        const url = URL.createObjectURL(new Blob([${JSON.stringify(source)}], {type: 'text/javascript'}));
        const worker = new Worker(url);
        worker.onmessage = event => { worker.terminate(); URL.revokeObjectURL(url); done(event.data); };
        worker.onerror = error => reject(new Error(error.message));
      })`);
      report(`Chrome worker, ${label}`, direct);
      await command('Emulation.setCPUThrottlingRate', {rate: 6});
      const slow = await evaluate(`(() => { ${worker}\nreturn ${run}; })()`);
      report(`Chrome page at 6× slowdown, ${label}`, slow);
      await command('Emulation.setCPUThrottlingRate', {rate: 1});
    }
  } finally {
    socket?.close();
    browser.kill();
    await exited;
    await rm(profile, {recursive: true, force: true, maxRetries: 10, retryDelay: 100});
  }
}
