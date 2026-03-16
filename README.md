# MorseDecode

A multi-channel Morse code (CW) decoder that processes audio in real time,
simultaneously decoding up to 12 CW signals across a configurable frequency
range via FFT bin analysis.

**Target performance:** < 5% Character Error Rate (CER), 5–50 WPM, including
signals sent with a "bad fist" (irregular timing).

---

## Features

| Feature | Details |
|---|---|
| Multi-channel | Up to 12 simultaneous bins (default: 12 × 50 Hz across 400–1000 Hz) |
| Audio input | Live device, audio file (WAV/FLAC), or stdin pipe (rtl_fm, gqrx, …) |
| Auto gain | Exponentially-weighted RMS AGC, configurable time constant |
| Auto threshold | Adaptive noise-floor estimation per bin, with hysteresis |
| Auto speed | Histogram peak-finding separates dits from dahs; 5–50 WPM |
| Auto spacing | Histogram-based inter-element / inter-letter / word-space thresholds |
| Bad-fist tolerant | Soft (sigmoid) dit/dah decisions; wide ambiguity zone; beam width 16 |
| Beam search | Branching hypothesis search with log-probability scoring and pruning |
| Prosigns | AR, SK, BT, KN, AS, CT, HH, SN, SOS |
| Rewind buffer | Buffers timing events; re-decodes from buffer when speed estimate updates |
| Speed reset | Resets estimator after configurable silence period; replays buffer |
| Live terminal UI | 12 always-visible lines via Rich; inactive bins dim and text scrolls off |
| File logging | Text or JSONL log with timestamp, frequency, decoded text, SNR, speed |
| Config system | 3-layer: default file → --config file → CLI flags |
| Cross-platform | Linux, Windows, macOS |

---

## Display

```
  Freq    SNR         Speed    Callsign   Decoded text
  425 Hz  ░░░░░ --dB  -- wpm             (dim — no signal)
  475 Hz  ▓▓▓░░ 18dB  15 wpm  W1AW       CQ CQ DE W1AW W1AW K
  525 Hz  ░░░░░ --dB  -- wpm
  ...
```

Each line shows:
- **Frequency** — bin centre in Hz
- **SNR bar + dB** — 5-block energy indicator + numeric SNR
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
│   └── detector.py        Adaptive noise-floor threshold + debounce → ON/OFF events
├── timing/
│   ├── segmenter.py       Run-length encoder; silence-reset detection
│   └── estimator.py       Log-histogram peak-finding → dit/dah/space thresholds
└── decoder/
    ├── morse_table.py     Full ITU table: letters, digits, punctuation, prosigns; Morse trie
    ├── buffer.py          Time-bounded ring buffer of TimingEvents for rewind
    └── beam_search.py     Soft-decision beam search; prosign-path branching; callsign extraction
```

### Signal pipeline (per audio chunk)

```
Audio chunk
  → AGCNormalizer          normalize RMS
  → STFTProcessor          overlap-add STFT → (n_frames × n_bins) energy array
  [per bin]
  → AdaptiveDetector       adaptive threshold + debounce → ON/OFF events
  → RunLengthSegmenter     ON/OFF events → TimingEvents; silence detection
  → TimingEstimator        histogram update → TimingEstimate (dit_ms, speed_wpm, …)
  → RewindBuffer           store events for re-decode on speed update
  → BeamDecoder            soft-decision beam search → decoded text + callsign
  → BinDisplayState        feed Rich live display + file logger
```

### Key design decisions for bad-fist tolerance

1. **Soft decisions** — P(dit) and P(dah) computed from a sigmoid centred on the
   estimated threshold, not a hard cut.  Near-threshold timings branch the beam.
2. **Wide ambiguity zone** — `ambiguity_factor` (default 1.5) scales the sigmoid
   width beyond the Gaussian prediction, allowing more branching.
3. **Robust histogram** — log-spaced bins, exponential decay, outlier trimming, and
   Gaussian smoothing before peak-finding.  Prevents a few rogue timings from
   skewing the speed estimate.
4. **Signal debounce** — short ON/OFF transitions (default 3 ms) are suppressed,
   handling key bounce and brief AGC artefacts.
5. **Rewind and replay** — when the speed estimate updates significantly (>15%),
   all buffered events are re-decoded with the new estimate.

---

## Installation

```bash
git clone https://github.com/parsimo2010/MorseDecode.git
cd MorseDecode
pip install -e .
```

For development (includes pytest):
```bash
pip install -e ".[dev]"
```

### Dependencies

| Package | Purpose |
|---|---|
| `numpy` / `scipy` | FFT, histogram, signal processing |
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

# Custom frequency range (600–900 Hz, 50 Hz bins → 6 channels)
morsedecode --freq-min 600 --freq-max 900 --bin-width 50

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
freq_min = 400       # Hz
freq_max = 1000      # Hz
bin_width = 50       # Hz  (12 bins)

[decoder]
beam_width = 16      # larger = better bad-fist tolerance (slower)
speed_min_wpm = 5.0
speed_max_wpm = 50.0
ambiguity_factor = 1.5   # widen dit/dah boundary (1.0 = standard)

[log]
enabled = false
path = "morsedecode.log"
format = "text"      # or "jsonl"
```

---

## Testing

```bash
pytest
pytest -v tests/test_morse_table.py   # Morse table + trie
pytest -v tests/test_timing.py        # Timing estimator
pytest -v tests/test_beam_search.py   # Beam decoder
```

---

## Roadmap

- [ ] CER test harness against known audio recordings
- [ ] Character language model (bigram) to improve ambiguous decoding
- [ ] TX logging (log sent CW for QSO script replay)
- [ ] Network audio input (UDP/TCP raw PCM)
- [ ] Web UI for remote monitoring
- [ ] GPU-accelerated FFT for very wide frequency ranges

---

## License

MIT
