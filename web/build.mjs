import {createHash} from 'node:crypto';
import {mkdir, readFile, writeFile} from 'node:fs/promises';

const output = new URL('../dist/', import.meta.url);
const read = name => readFile(new URL(name, import.meta.url));
const asText = buffer => buffer.toString('utf8').replaceAll('\r\n', '\n');

function replaceRequired(source, search, replacement) {
  if (!source.includes(search)) throw new Error(`Build marker missing: ${search}`);
  return source.replace(search, () => replacement);
}

const [template, css, app, decoder, worker, capture, serviceWorker] = (await Promise.all([
  'index.html', 'style.css', 'app.mjs', '../morse_decode/core/decoder.mjs', 'worker.mjs', 'capture.mjs', 'service-worker.js'
].map(read))).map(asText);

// The portable page starts both audio processors from inline source. The
// decoder and worker can still use ordinary module imports in source tooling.
const workerBundle = [
  replaceRequired(decoder, 'export {CWDecoder, MORSE};', ''),
  replaceRequired(worker, "import {CWDecoder} from '../morse_decode/core/decoder.mjs';", '')
].join('\n');
const script = [
  '"use strict";',
  `const workerSource = ${JSON.stringify(workerBundle)};`,
  `const captureSource = ${JSON.stringify(capture)};`,
  app
].join('\n').replace(/<\/script/gi, '<\\/script');
const html = replaceRequired(
  replaceRequired(template, '<!-- styles -->', `<style>\n${css}</style>`),
  '<!-- scripts -->', `<script>\n${script}</script>`
);

const paths = ['manifest.webmanifest', 'icons/app-192.png', 'icons/app-512.png', 'icons/apple.png'];
const files = await Promise.all(paths.map(read));
const revision = createHash('sha256');
for (const file of [html, serviceWorker, ...files]) revision.update(file);
const offline = replaceRequired(serviceWorker, '__REVISION__', revision.digest('hex').slice(0, 16));

await mkdir(new URL('icons/', output), {recursive: true});
await Promise.all([
  writeFile(new URL('index.html', output), html),
  writeFile(new URL('service-worker.js', output), offline),
  ...files.map((file, i) => writeFile(new URL(paths[i], output), file))
]);
console.log(`Built ${new URL('index.html', output).href}`);
