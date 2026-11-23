const field = id => document.getElementById(id);
const device = field('device');
const status = field('status');
const transcript = field('transcript');
const tabInput = 'browser-tab';
const media = navigator.mediaDevices;
const supportsTabAudio = Boolean(media?.getDisplayMedia && media.getSupportedConstraints().suppressLocalAudioPlayback);
let active;
let previous = '';
let latest = '';
let offset = 0;

function scriptURL(source) {
  return URL.createObjectURL(new Blob([source], {type: 'text/javascript'}));
}

async function listDevices() {
  if (!media) return;
  const inputs = (await media.enumerateDevices().catch(() => [])).filter(item => item.kind === 'audioinput' &&
    item.deviceId && item.deviceId !== 'default');
  const selected = device.value;
  const options = [new Option('System default', '')];
  if (supportsTabAudio) options.push(new Option('Browser tab audio', tabInput));
  options.push(...inputs.map((item, i) => new Option(item.label || 'Audio input ' + (i + 1), item.deviceId)));
  device.replaceChildren(...options);
  if (options.some(option => option.value === selected)) device.value = selected;
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

function startCapture(session) {
  const source = session.context.createMediaStreamSource(session.stream);
  const capture = new AudioWorkletNode(session.context, 'morse-capture', {channelCount: 1, channelCountMode: 'explicit'});
  session.capture = capture;
  capture.addEventListener('processorerror', () => cleanup(session, 'The audio capture processor failed.'));
  capture.port.onmessage = ({data: samples}) => {
    if (active !== session) return;
    if (samples === null) {
      capture.port.close();
      source.disconnect();
      capture.disconnect();
      session.worker.postMessage({type: 'stop'});
    } else {
      session.worker.postMessage({type: 'audio', samples}, [samples.buffer]);
    }
  };
  source.connect(capture);
  // The worklet writes zeros to its output, keeping the capture graph
  // active without feeding the microphone back through the speakers.
  capture.connect(session.context.destination);
  field('stop').disabled = false;
  status.textContent = 'Listening for a keyed carrier…';
}

field('start').onclick = async () => {
  if (active) return;
  const low = field('low').valueAsNumber;
  const high = field('high').valueAsNumber;
  if (!(low >= 100 && high <= 3000 && low < high)) {
    status.textContent = 'Enter an increasing frequency range between 100 and 3000 Hz.';
    return;
  }
  const fromTab = device.value === tabInput;
  if (!(fromTab ? supportsTabAudio : media?.getUserMedia)) {
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
  status.textContent = fromTab ? 'Choose the WebSDR tab and enable tab audio…' : 'Waiting for audio input permission…';
  try {
    session.context = new AudioContext();
    if (fromTab) {
      // The browser requires this call during the Start button gesture.
      session.stream = await media.getDisplayMedia({
        video: {displaySurface: 'browser'},
        audio: {suppressLocalAudioPlayback: false},
        selfBrowserSurface: 'exclude',
        monitorTypeSurfaces: 'exclude',
        systemAudio: 'exclude',
        surfaceSwitching: 'exclude'
      });
      const [video] = session.stream.getVideoTracks();
      if (video?.getSettings().displaySurface !== 'browser' || !session.stream.getAudioTracks().length) {
        throw new Error('Select a browser tab and turn on Also share tab audio.');
      }
      // Display capture requires video in the request. The decoder uses the audio track alone.
      video.stop();
    }
    await session.context.resume();
    if (!fromTab) {
      const audio = {echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1};
      if (device.value) audio.deviceId = {exact: device.value};
      session.stream = await media.getUserMedia({audio});
    }
    const [track] = session.stream.getAudioTracks();
    track.addEventListener('ended', () => {
      if (active !== session) return;
      if (session.capture) stop();
      else cleanup(session, 'Audio input stopped.');
    }, {once: true});
    if (track.readyState !== 'live') throw new Error('The audio input stopped before decoding began.');
    // A data URL also works when the HTML file has an opaque local origin.
    await session.context.audioWorklet.addModule('data:text/javascript,' + encodeURIComponent(captureSource));
    if (active !== session) return;
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
        try {
          startCapture(session);
        } catch (error) {
          cleanup(session, 'Could not start audio capture. ' + error.message);
        }
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
media?.addEventListener('devicechange', () => listDevices().catch(() => {}));
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
