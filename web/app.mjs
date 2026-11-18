const field = id => document.getElementById(id);
const device = field('device');
const status = field('status');
const transcript = field('transcript');
let active;
let previous = '';
let latest = '';
let offset = 0;

function scriptURL(source) {
  return URL.createObjectURL(new Blob([source], {type: 'text/javascript'}));
}

async function listDevices() {
  if (!navigator.mediaDevices) return;
  const selected = device.value;
  const inputs = (await navigator.mediaDevices.enumerateDevices()).filter(item => item.kind === 'audioinput' &&
    item.deviceId && item.deviceId !== 'default');
  device.replaceChildren(new Option('System default', ''),
    ...inputs.map((item, i) => new Option(item.label || 'Audio input ' + (i + 1), item.deviceId)));
  if (inputs.some(item => item.deviceId === selected)) device.value = selected;
}

function render(result) {
  latest = result.text;
  const scroll = transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 32;
  const text = latest.slice(offset).trimStart();
  field('committed').textContent = [previous, text].filter(Boolean).join('\n');
  field('preview').textContent = text ? result.preview : result.preview.trimStart();
  field('frequency').textContent = result.frequency ? Math.round(result.frequency) + ' Hz' : '—';
  field('speed').textContent = result.wpm ? result.wpm.toFixed(1) + ' WPM' : '—';
  if (scroll) transcript.scrollTop = transcript.scrollHeight;
}

function busy(value) {
  for (const id of ['device', 'low', 'high', 'start']) field(id).disabled = value;
}

async function cleanup(session, message) {
  if (active !== session) return;
  session.worker?.terminate();
  session.stream?.getTracks().forEach(track => track.stop());
  active = undefined;
  field('stop').disabled = true;
  busy(false);
  status.textContent = message;
  if (session.context && session.context.state !== 'closed') await session.context.close();
}

function stop() {
  if (!active?.capture || active.stopping) return;
  active.stopping = true;
  field('stop').disabled = true;
  status.textContent = 'Finishing transcript…';
  active.capture.port.postMessage('flush');
}

field('start').onclick = async () => {
  if (active) return;
  const low = field('low').valueAsNumber;
  const high = field('high').valueAsNumber;
  if (!(low >= 100 && high <= 3000 && low < high)) {
    status.textContent = 'Enter an increasing frequency range between 100 and 3000 Hz.';
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    status.textContent = 'Open the HTTPS site or use localhost to enable microphone access.';
    return;
  }
  if (!window.AudioContext || !window.AudioWorkletNode) {
    status.textContent = 'Use a current version of Chrome, Edge, Firefox, or Safari for live audio.';
    return;
  }
  const session = {};
  active = session;
  previous = field('committed').textContent;
  latest = '';
  offset = 0;
  render({text: '', preview: ''});
  busy(true);
  status.textContent = 'Waiting for audio input permission…';
  try {
    session.context = new AudioContext();
    await session.context.resume();
    const audio = {echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1};
    if (device.value) audio.deviceId = {exact: device.value};
    session.stream = await navigator.mediaDevices.getUserMedia({audio});
    // A data URL also works when the HTML file has an opaque local origin.
    await session.context.audioWorklet.addModule('data:text/javascript,' + encodeURIComponent(captureSource));
    const workerURL = scriptURL(workerSource);
    try {
      session.worker = new Worker(workerURL);
    } finally {
      URL.revokeObjectURL(workerURL);
    }
    session.worker.onerror = () => cleanup(session, 'The decoding worker failed to load.');
    session.worker.onmessage = ({data}) => {
      if (active !== session) return;
      if (data.type === 'ready') {
        const source = session.context.createMediaStreamSource(session.stream);
        session.capture = new AudioWorkletNode(session.context, 'morse-capture');
        session.capture.port.onmessage = ({data: samples}) => {
          if (samples === null) {
            source.disconnect();
            session.capture.disconnect();
            session.worker.postMessage({type: 'stop'});
          } else {
            session.worker.postMessage({type: 'audio', samples}, [samples.buffer]);
          }
        };
        source.connect(session.capture);
        // The worklet writes zeros to its output, keeping the capture graph
        // active without feeding the microphone back through the speakers.
        session.capture.connect(session.context.destination);
        session.stream.getAudioTracks()[0].onended = stop;
        field('stop').disabled = false;
        status.textContent = 'Listening for a keyed carrier…';
      } else if (data.type === 'error') {
        cleanup(session, data.message);
      } else {
        render(data);
        if (data.type === 'finished') cleanup(session, 'Stopped.');
        else if (!session.stopping) status.textContent = data.frequency ? 'Listening · carrier acquired' : 'Listening for a keyed carrier…';
      }
    };
    session.worker.postMessage({type: 'start', rate: session.context.sampleRate, passband: {low, high}});
    listDevices().catch(() => {});
  } catch (error) {
    await cleanup(session, 'Could not start audio capture. ' + error.message);
  }
};
field('stop').onclick = stop;
field('clear').onclick = () => {
  previous = '';
  offset = latest.length;
  field('committed').textContent = '';
  field('preview').textContent = '';
};
navigator.mediaDevices?.addEventListener('devicechange', () => listDevices().catch(() => {}));
listDevices().catch(() => {});

if (location.protocol === 'https:' || location.protocol === 'http:') {
  for (const [rel, href] of [['manifest', './manifest.webmanifest'], ['apple-touch-icon', './icons/apple.png']]) {
    const link = document.createElement('link');
    link.rel = rel;
    link.href = href;
    document.head.append(link);
  }
  if (navigator.serviceWorker) {
    navigator.serviceWorker.register('./service-worker.js').catch(error => {
      console.warn('Offline startup is unavailable.', error);
    });
  }
}
