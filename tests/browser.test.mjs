import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {runInNewContext} from 'node:vm';

const read = name => readFileSync(new URL('../web/' + name, import.meta.url), 'utf8');

test('the capture worklet sends its tail once and ignores audio after flush', () => {
  const sent = [];
  let Capture;
  runInNewContext(read('capture.mjs'), {
    AudioWorkletProcessor: class {
      port = {postMessage: block => sent.push(block === null ? null : Array.from(block))};
    },
    registerProcessor: (_, processor) => { Capture = processor; }
  });
  const capture = new Capture();
  assert.equal(capture.process([[Float32Array.of(0.25, 0.5)]]), true);
  capture.port.onmessage({data: 'flush'});
  assert.equal(capture.process([[new Float32Array(2048)]]), false);
  capture.port.onmessage({data: 'flush'});
  assert.deepEqual(sent, [[0.25, 0.5], null]);
});

test('a failed audio graph stops the track and unlocks the controls', async () => {
  const fields = new Map(['device', 'status', 'transcript', 'committed', 'preview',
    'frequency', 'speed', 'start', 'stop', 'clear', 'low', 'high'].map(id => [id, {textContent: ''}]));
  fields.get('low').valueAsNumber = 400;
  fields.get('high').valueAsNumber = 1000;
  const released = [];
  const track = {readyState: 'live', addEventListener() {}, stop: () => released.push('track')};
  let worker;
  class AudioContext {
    audioWorklet = {addModule: async () => {}};
    resume() {}
    createMediaStreamSource() { throw new Error('graph failed'); }
    close() { released.push('context'); }
  }
  class AudioWorkletNode {}
  runInNewContext(read('app.mjs'), {
    document: {getElementById: id => fields.get(id)},
    navigator: {mediaDevices: {
      getUserMedia: async () => ({getAudioTracks: () => [track], getTracks: () => [track]}),
      enumerateDevices: async () => [],
      addEventListener() {}
    }},
    location: {protocol: 'file:'},
    window: {AudioContext, AudioWorkletNode},
    AudioContext,
    AudioWorkletNode,
    Worker: class {
      constructor() { worker = this; }
      postMessage() {}
      terminate() { released.push('worker'); }
    },
    URL, Blob, workerSource: '', captureSource: ''
  });
  await fields.get('start').onclick();
  assert.equal(fields.get('start').disabled, true);
  worker.onmessage({data: {type: 'ready'}});
  assert.deepEqual(released, ['worker', 'track', 'context']);
  assert.equal(fields.get('start').disabled, false);
  assert.equal(fields.get('stop').disabled, true);
  assert.match(fields.get('status').textContent, /graph failed/);
});
