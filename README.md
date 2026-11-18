# MorseDecode

MorseDecode decodes keyed Morse code (CW) in real time. The browser app and
terminal UI use the same JavaScript decoder. The browser follows one carrier
inside the selected passband. The terminal can run several passbands in parallel.

## Browser app

Build the static files with Node.js 24 from the checkout. The build has no
package dependencies.

```bash
node web/build.mjs
```

Double-click `dist/index.html` to open it in desktop Chrome. You can copy this
single HTML file to another computer. The stylesheet, decoder, and audio
capture code are embedded, and decoding runs locally in the browser.

Select an audio input, click **Start listening**, and grant microphone access.
Play a keyed CW signal within the selected frequency range (400–1000 Hz by
default). The page shows the carrier frequency estimate, speed in WPM, and
transcript. Click **Stop** to finalize the transcript. If the browser blocks
microphone access for a local file, serve `dist/` on localhost and open
`http://127.0.0.1:8000/`.

```bash
python -m http.server 8000 --bind 127.0.0.1 --directory dist
```

### Publish and install on a phone

Serve the contents of `dist/` over HTTPS on any static host. For GitHub Pages,
choose **GitHub Actions** under **Settings → Pages → Build and deployment**,
then run **Publish MorseDecode to GitHub Pages** from the **Actions** tab. Run
the workflow again for updates. With default project Pages settings, the URL is
`https://parsimo2010.github.io/MorseDecode/`. GitHub Pages on a private repository
requires an eligible plan. The workflow uploads only the static build output.
[GitHub Pages publishing guide](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)

- **Android (Chrome)** — Open the HTTPS page, open the three-dot menu, and choose
  **Install app** or the install option under **Add to Home screen**. [Chrome help](https://support.google.com/chrome/answer/9658361?co=GENIE.Platform%3DAndroid)
- **iPhone (Safari)** — Open the HTTPS page, tap **Share**, choose **Add to Home
  Screen**, enable **Open as Web App** if offered, and tap **Add**. [Apple help](https://support.apple.com/guide/iphone/open-as-web-app-iphea86e5236/ios)

Open the app and allow microphone access when prompted. Keep the app in the
foreground while listening. After the first online load finishes caching the
app, it can reopen offline.

## Terminal UI

Install Python 3.10+ and Node.js 24, with `node` on your PATH. From the checkout:

```bash
python -m pip install -e .
morsedecode --help
```

The terminal takes audio from a device, a file supported by libsndfile, or a
raw PCM stream. Its Rich display shows each passband's current carrier, signal
contrast, estimated speed, detected callsign, and decoded text.

```bash
morsedecode --list-devices
morsedecode
morsedecode --device 3
morsedecode --file recording.wav
rtl_fm -f 7.040M -s 44100 -g 30 | morsedecode --stdin --sample-rate 44100
morsedecode --file recording.wav --log decode.log --log-format jsonl
```

The stdin format is signed 16-bit little-endian mono PCM. It defaults to
44,100 Hz. The receiver defaults to three 200 Hz passbands over 400–1000 Hz.
To match the browser's default single passband, use:

```bash
morsedecode --freq-min 400 --freq-max 1000 --channel-width 600
```

Identical PCM samples, sample rate, and decoder settings produce the same
results regardless of input chunk size. Browser and terminal capture can use
different devices or sample rates. Keep terminal AGC off, its default, when
comparing identical raw audio.

### Configuration

Use [morsedecode.example.toml](morsedecode.example.toml) as a reference. The
default config is `%APPDATA%\morsedecode\config.toml` on Windows,
`$XDG_CONFIG_HOME/morsedecode/config.toml` if XDG is configured, or
`~/.morsedecode.toml` otherwise. An explicit `--config` file overrides the
default file, and CLI flags take precedence over both.

The shared core supplies defaults for both interfaces. It uses a 50 ms Hann
analysis window, 5 ms hop, and search-tone spacing of at most 12 Hz. `--on-db` and `--off-db` retain the
historical 24/20 sensitivity scale. Lower values increase sensitivity.
Older beam-width, histogram, ambiguity, and rewind settings belonged to
the previous decoder and can be removed from existing TOML files.
The legacy `--beam-width` flag is accepted with a warning.

## Shared decoder

[`morse_decode/core/decoder.mjs`](morse_decode/core/decoder.mjs) is the
reference implementation. It analyzes audio around candidate carriers,
tracks keying speed from recent marks and gaps, and searches possible Morse
character boundaries across each word. A word in progress can be reinterpreted
as the timing estimate updates. The terminal routes PCM through a persistent
Node.js process. The web build embeds the same module in its audio worker.

Changes to detection, timing, or Morse decoding belong in that module. Rebuild
the static HTML with `node web/build.mjs` after changing it and rerun the Pages
workflow to update a published site.

## Testing

```bash
python -m pip install -e ".[dev]"
python -m pytest
node tests/performance.mjs
```

The terminal integration tests exercise file and stdin input, multiple
simultaneous carriers, final transcript logging, and exact parity with the
web worker built into the standalone HTML. The shared decoder regression
suite measures character error rate on seeded CW audio with noise, changing
speed, timing jitter, fading, and interference.

Ongoing work is tracked in the [GitHub issue tracker](https://github.com/parsimo2010/MorseDecode/issues).

## License

MIT
