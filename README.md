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

Open `dist/index.html` in desktop Chrome. You can copy this single HTML file
to another computer. The stylesheet, decoder, and audio capture code are
embedded. The browser processes the audio locally and runs without Node.js
or Python after the build.

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
  Screen**, enable **Open as Web App** if offered, and tap **Add**. [Apple help](https://support.apple.com/guide/iphone/open-as-web-app-iphea86e5236/27/ios/27)

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
morsedecode --device "Microphone (Senary Audio), MME"
morsedecode --file recording.wav
morsedecode --stdin --sample-rate 44100 < recording.pcm
morsedecode --file recording.wav --log decode.log --log-format jsonl
```

Use a device name from `--list-devices`. If several devices match the name,
append the host API shown in the error, as in the example above.

Stdin expects raw signed 16-bit mono PCM in the host's byte order
(little-endian on Windows). Set `--sample-rate` to match the stream.
Stdin defaults to 44,100 Hz. Live input uses the device's default rate unless
you override it, and file input uses the recording's rate. From PowerShell,
run the stdin example through Command Prompt.

```powershell
cmd.exe /c 'morsedecode --stdin --sample-rate 44100 < recording.pcm'
```

The terminal defaults to three 200 Hz passbands over 400–1000 Hz. Use this
command to match the browser's default single passband.

```bash
morsedecode --freq-min 400 --freq-max 1000 --channel-width 600
```

Identical PCM samples, sample rate, and decoder settings produce the same
results regardless of input chunk size. For the same behavior, match the
passband and leave terminal decoder overrides unset. Both interfaces inherit
the core's defaults, including automatic gain control (AGC) off.

### Configuration

Use [morsedecode.example.toml](morsedecode.example.toml) as a reference. The
terminal loads `%APPDATA%\morsedecode\config.toml` on Windows. On macOS and
Linux it loads `$XDG_CONFIG_HOME/morsedecode/config.toml` when
`XDG_CONFIG_HOME` is set and `~/.morsedecode.toml` otherwise. An explicit
`--config` file overrides the default file, and CLI flags override the
corresponding settings. If multiple input sources are configured, file input
takes precedence over stdin, followed by live device input.

The shared core supplies defaults for both interfaces. It searches for carriers
with a 50 ms Hann window, a 5 ms hop, and search-tone spacing of at most 12 Hz.
Once it finds a carrier, it can use a shorter window for fast elements or a
longer one for weak signals. Lower
`--on-db` and `--off-db` values increase sensitivity on the historical 24/20
scale. The JSONL field `snr_db` reports the decoder's signal contrast in dB.

Remove `beam_width`, `histogram_bins`, `estimator_decay`, `outlier_pct`,
`silence_reset_s`, `rewind_buffer_s`, and `ambiguity_factor` from older TOML
files. The current decoder ignores these retired settings. The legacy
`--beam-width` flag is accepted with a warning.

## Shared decoder

[`morse_decode/core/decoder.mjs`](morse_decode/core/decoder.mjs) is the
reference implementation. It downsamples with an anti-alias filter where the
passband permits, follows the carrier as its pitch drifts, and adapts detection
to fades and bursts of noise. It can use carrier phase when it remains stable
through keying gaps. It tracks dot and dash timing separately from character
spacing and scores possible Morse sequences by their timing. A compact history
lets the browser revise the current word until it is ready to commit. The
terminal routes PCM to the core through a persistent Node.js process. The web
build embeds the same module in a dedicated worker. An AudioWorklet captures
and forwards browser audio.

Changes to gain control, detection, timing, or Morse decoding belong in that
module. Rebuild the static HTML with `node web/build.mjs` after changing it and
rerun the Pages workflow to update a published site.

## Testing

```bash
python -m pip install -e ".[dev]"
python -m pytest
node tests/performance.mjs
node tests/accuracy.mjs --holdout --baseline=6b2ba41
python tests/recordings.py --baseline 6b2ba41
node tests/realtime.mjs --baseline=6b2ba41
```

The terminal integration tests exercise file and stdin input, multiple
simultaneous carriers, final transcript logging, and exact parity with the
web worker built into the standalone HTML. The shared decoder regression
suite measures character error rate on seeded CW audio with noise, changing
speed, timing jitter, fading, and interference. The recordings benchmark
downloads public W1AW practice recordings and their transcripts. See the
[benchmark results and methodology](docs/decoder-benchmarks.md) for accuracy,
real-time costs, and how to repeat the browser measurement.

Ongoing work is tracked in the [GitHub issue tracker](https://github.com/parsimo2010/MorseDecode/issues).

## License

MIT
