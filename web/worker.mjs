import {CWDecoder} from './decoder.mjs';

let decoder;
let lastUpdate = 0;
self.onmessage = ({data}) => {
  try {
    switch (data.type) {
      case 'start':
        decoder = new CWDecoder(data.rate, data.passband);
        self.postMessage({type: 'ready'});
        break;
      case 'audio':
        decoder.push(data.samples);
        if (performance.now() - lastUpdate >= 120) {
          self.postMessage({type: 'update', ...decoder.snapshot()});
          lastUpdate = performance.now();
        }
        break;
      case 'stop':
        self.postMessage({type: 'finished', ...decoder.finish()});
        break;
    }
  } catch (error) {
    self.postMessage({type: 'error', message: error.message});
  }
};
