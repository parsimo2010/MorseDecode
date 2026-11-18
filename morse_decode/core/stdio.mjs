import {createInterface} from 'node:readline';
import {stdin, stdout} from 'node:process';
import {CWDecoder} from './decoder.mjs';

let channels;

function update(channel, finish) {
  const snapshot = finish ? channel.decoder.finish() : channel.decoder.snapshot();
  const delta = snapshot.text.slice(channel.offset);
  channel.offset = snapshot.text.length;
  const {frequency, wpm, callsign, signalDb, active} = snapshot;
  return {frequency, wpm, callsign, signalDb, active, delta};
}

const requests = createInterface({input: stdin, crlfDelay: Infinity});
for await (const line of requests) {
  try {
    const request = JSON.parse(line);
    if (request.type === 'start') {
      const guard = request.passbands.length > 1;
      channels = request.passbands.map((band, i) => ({
        decoder: new CWDecoder(request.rate, {
          ...request.options, ...band, guard, includeHigh: i === request.passbands.length - 1
        }),
        offset: 0
      }));
      stdout.write('{}\n');
    } else {
      const finish = request.type === 'finish';
      if (!finish) {
        const pcm = Buffer.from(request.pcm, 'base64');
        const samples = Float32Array.from({length: pcm.length / 4}, (_, i) => pcm.readFloatLE(i * 4));
        for (const {decoder} of channels) decoder.push(samples);
      }
      stdout.write(JSON.stringify({channels: channels.map(channel => update(channel, finish))}) + '\n');
      if (finish) break;
    }
  } catch (error) {
    stdout.write(JSON.stringify({error: error.message}) + '\n');
    break;
  }
}
requests.close();
