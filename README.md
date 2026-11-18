# MorseDecode

MorseDecode decodes Morse code (CW) from audio in real time. The browser app
follows one carrier from a microphone or audio input. The Python CLI processes
multiple frequency channels and also accepts files and raw PCM on stdin.

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

---

## Python CLI features

| Feature | Details |
|---|---|
| Multi-channel | Configurable channel count (default: 3 × 200 Hz across 400–1000 Hz) |
| Audio input | Live device, audio file (WAV/FLAC), or stdin pipe (rtl_fm, gqrx, …) |
| Auto gain | Optional exponentially weighted RMS AGC with a configurable time constant |
| Ratio detection | Schmitt trigger on the strongest FFT bin relative to the lower-energy bins |
| Mark confidence | Average ratio over each mark's duration → beam-search weight; marginal detections discounted |
| Auto speed | Histogram valley detection separates dits from dahs; 5–50 WPM |
| Auto spacing | Histogram-based inter-element / inter-letter / word-space thresholds |
| Bad-fist tolerant | Soft (sigmoid) dit/dah decisions; mark-confidence noise branching; beam width 16 |
| Beam search | Branching hypothesis search with log-probability scoring and pruning |
| Prosigns | AR, SK, BT, KN, AS, CT, SN |
| Rewind buffer | Buffers timing events; re-decodes from buffer when speed estimate updates |
| Speed reset | Resets estimator after configurable silence period; replays buffer |
| Live terminal UI | Per-channel rows via Rich; inactive channels dim and text scrolls off |
| File logging | Text and JSONL logs include timestamp, frequency, speed, and decoded text. JSONL also includes the signal ratio in dB. |
| Config system | 3-layer: default file → --config file → CLI flags |
| Cross-platform | Linux, Windows, macOS |

---

## Display

```
  Freq    SNR         Speed    Callsign   Decoded text
  499 Hz  ..... --dB  -- wpm             (dim — no signal)
  699 Hz  ##### 28dB  25 wpm  W1AW       CQ CQ DE W1AW W1AW K
  899 Hz  ..... --dB  -- wpm
```

Each line shows:
- **Frequency** — channel centre in Hz
- **SNR bar + dB** — 5-block bar + numeric ratio (dB); reflects bin1/noise_ref ratio
- **Speed** — estimated CW speed in WPM
- **Callsign** — last callsign detected in decoded text (matches `DE CALL` or standalone)
- **Decoded text** — scrolling window of decoded output

---

## Architecture

```
morse_decode/
├── config.py              3-layer TOML + CLI config system
├── cli.py                 Click CLI entry point + main processing loop
├── audio/
│   ├── source.py          Device / file / stdin audio sources (sounddevice + soundfile)
│   └── normalizer.py      Exponentially-weighted RMS AGC
├── signal/
│   ├── fft.py             Overlap-add STFT; per-bin energy extraction
│   └── detector.py        Ratio-based Schmitt trigger + debounce → ON/OFF events with confidence
├── timing/
│   ├── segmenter.py       ON/OFF events → TimingEvents with mark_confidence; silence reset
│   └── estimator.py       Log-histogram valley detection → dit/dah/space thresholds
└── decoder/
    ├── morse_table.py     Letters, digits, selected punctuation and prosigns; Morse trie
    ├── buffer.py          Time-bounded ring buffer of TimingEvents for rewind
    └── beam_search.py     Soft-decision beam search; noise-branch on low confidence; callsign
```

### Signal pipeline (per audio chunk)

```
Audio chunk
  → AGCNormalizer          normalize RMS
  → STFTProcessor          overlap-add STFT → (n_frames × n_bins) energy array
  [per channel]
  → GatedNoiseDetector     ratio Schmitt trigger + debounce → ON/OFF events + avg_ratio_db
  → RunLengthSegmenter     ON/OFF events → TimingEvents with mark_confidence; silence detection
  → TimingEstimator        histogram update → TimingEstimate (dit_ms, speed_wpm, thresholds)
  → RewindBuffer           store events for re-decode on speed update
  → BeamDecoder            soft-decision + noise-branch beam search → decoded text + callsign
  → BinDisplayState        feed Rich live display + file logger
```

### Key design decisions

1. **Ratio-based detection** — instead of tracking an adaptive noise floor (which fails when
   radio AGC amplifies in-band noise during silence), detection uses
   `10*log10(bin1 / mean(lower_half_bins))`.  A CW signal concentrates in 1–2 FFT bins;
   the lower half of the channel's bins supplies a noise reference, making the ratio
   insensitive to uniform gain changes.

2. **Schmitt trigger hysteresis** — ON threshold (24 dB) > OFF threshold (20 dB).
   Once a mark starts, signal can fade to 20 dB before the detector goes OFF, suppressing
   mid-element chatter.

3. **Mark confidence** — the average ratio during each mark is converted to a probability
   via a sigmoid centred on the ON threshold.  Strong signals → confidence ≈ 1.0;
   marginal detections → confidence < 0.5.  The beam decoder branches on "this was noise"
   for low-confidence marks, weighted by `log(1 - confidence)`.

4. **Soft dit/dah decisions** — P(dit) and P(dah) computed from a sigmoid centred on the
   estimated threshold, not a hard cut.  Near-threshold timings branch the beam.

5. **Robust histogram** — log-spaced bins, exponential decay, outlier trimming, and Gaussian
   smoothing before peak-finding.  Prevents a few rogue timings from skewing the speed estimate.

6. **Rewind and replay** — when the speed estimate updates significantly (>15%), all buffered
   events are re-decoded with the new estimate.

---

## Installation

```bash
git clone https://github.com/parsimo2010/MorseDecode.git
cd MorseDecode
python -m pip install -e .
```

For development (includes pytest):
```bash
python -m pip install -e ".[dev]"
```

### Dependencies

| Package | Purpose |
|---|---|
| `numpy` | FFT, histogram, signal processing |
| `scipy` | Signal-processing dependency |
| `sounddevice` | Cross-platform live audio capture |
| `soundfile` | Audio file decoding (WAV, FLAC, OGG) |
| `rich` | Live multi-line terminal UI |
| `click` | CLI argument parsing |
| `tomli` | TOML config parsing (Python < 3.11) |

---

## Usage

```bash
# List audio input devices
morsedecode --list-devices

# Decode from system default microphone
morsedecode

# Decode from a specific device (by index from --list-devices)
morsedecode --device 3

# Decode an audio file
morsedecode --file recording.wav

# Pipe from rtl_fm (stdin, signed 16-bit 44100 Hz mono)
rtl_fm -f 7.040M -s 44100 -g 30 | morsedecode --stdin

# Custom frequency range (625–825 Hz, single 200 Hz channel)
morsedecode --freq-min 625 --freq-max 825

# Tighten detection thresholds for a clean, strong signal
morsedecode --on-db 30 --off-db 24

# Loosen thresholds for a weak or noisy signal
morsedecode --on-db 18 --off-db 12

# Use a specific config file
morsedecode --config ~/my-radio.toml

# Enable file logging
morsedecode --log decode.log --log-format jsonl

# Widen speed range for contest traffic
morsedecode --speed-min 5 --speed-max 50
```

---

## Configuration

Three sources, highest priority first:

1. **CLI flags** — individual `--device`, `--freq-min`, etc.
2. **Explicit config file** — `--config path/to/file.toml`
3. **Default config file** — `~/.morsedecode.toml` (Linux/Mac) or
   `%APPDATA%\morsedecode\config.toml` (Windows)

Copy `morsedecode.example.toml` to get started:
```bash
cp morsedecode.example.toml ~/.morsedecode.toml
```

Key config sections:

```toml
[input]
freq_min = 400        # Hz — lower edge of frequency range
freq_max = 1000       # Hz — upper edge
bin_width = 25        # Hz — FFT bin width (sets frequency resolution)
channel_width_hz = 200  # Hz — decoding channel width (must be multiple of bin_width)

[audio]
window_ms = 40.0      # FFT window (40 ms → 25 Hz bins at any sample rate)
hop_ms = 5.0          # FFT hop (time resolution; smaller = better at high WPM)
on_db = 24.0          # ON  threshold: 10*log10(bin1/noise_ref) in dB
off_db = 20.0         # OFF threshold (hysteresis gap prevents chatter)

[decoder]
beam_width = 16       # larger = better bad-fist tolerance (slower)
speed_min_wpm = 5.0
speed_max_wpm = 50.0
ambiguity_factor = 1.5  # widen dit/dah boundary (1.0 = standard)

[log]
enabled = false
path = "morsedecode.log"
format = "text"       # or "jsonl"
```

### Detection threshold tuning

The detector uses `10*log10(bin1 / mean(lower_half_bins))` as its metric.
Typical values for the 700 Hz channel on a 20 dB SNR CW signal: **28–32 dB** during a mark,
**2–5 dB** during silence.

| Scenario | Recommended `on_db` / `off_db` |
|---|---|
| Strong signal, clean band | 28 / 24 |
| Normal HF conditions | 24 / 20 (default) |
| Weak or QRM-heavy signal | 18 / 12 |

---

## Testing

```bash
python -m pytest
node tests/performance.mjs
```

The browser suite reports character error rate on seeded synthetic CW and checks
timing, frequency acquisition, and behavior under noise, jitter, and fading.
The Python diagnostic `python test_decoder.py` runs synthetic examples and can
also analyze a recording passed as an argument.

Ongoing work is tracked in the [GitHub issue tracker](https://github.com/parsimo2010/MorseDecode/issues).

---

## License

MIT
