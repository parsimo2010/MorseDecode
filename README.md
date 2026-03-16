# MorseDecode

A multi-channel Morse code decoder that processes audio streams in real time, decoding
CW (Continuous Wave) transmissions across multiple simultaneous frequency bins.

## Overview

MorseDecode performs an FFT over a configurable frequency range (default 400–1000 Hz)
in 50 Hz bins, decoding each bin as an independent CW stream. This allows decoding
multiple simultaneous transmissions on different tones in a single audio feed.

**Target performance:** < 5% Character Error Rate (CER) across 5–50 WPM signals.

## Features

- **Multi-channel decoding** — up to 12+ simultaneous CW streams via FFT bin analysis
- **Streaming audio** — live input from selectable audio device
- **File input** — decode WAV/FLAC/MP3 audio files at any sample rate
- **Auto-normalization** — handles quiet signals by normalizing input volume
- **Auto speed detection** — histogram-based separation of dits vs. dahs; range 5–50 WPM
- **Auto threshold** — noise floor estimation drives signal detection threshold
- **Auto spacing** — histogram separation of inter-element, inter-letter, and word spaces
- **Beam search decoder** — maintains top-k hypotheses through ambiguous timings
- **Speed reset** — resets estimator after long silence; buffers early audio for re-decode
- **Multi-line terminal UI** — one live-updating line per active frequency bin
- **Cross-platform** — Linux, Windows, macOS

## Planned Architecture

```
morse_decode/
├── audio/
│   ├── source.py        # Device enumeration, streaming, file playback
│   └── normalizer.py    # RMS-based auto gain control
├── signal/
│   ├── fft.py           # Windowed FFT, per-bin energy extraction
│   └── detector.py      # Adaptive threshold, signal on/off events
├── timing/
│   ├── estimator.py     # Histogram-based dit/dah/space timing estimation
│   └── segmenter.py     # Run-length encoder → timing symbol stream
├── decoder/
│   ├── morse_table.py   # Full character/prosign lookup table
│   ├── beam_search.py   # Beam search over morse tree with rewind buffer
│   └── buffer.py        # Ring buffer for re-decoding on speed update
├── output/
│   └── display.py       # Rich/curses multi-line live terminal output
└── cli.py               # Click-based CLI entry point
```

## Installation

```bash
pip install -e .
```

## Usage

```bash
# List available audio devices
morsedecode --list-devices

# Decode from default audio device
morsedecode

# Decode from a specific device
morsedecode --device 3

# Decode an audio file
morsedecode --file recording.wav

# Customize frequency range and bin width
morsedecode --freq-min 400 --freq-max 1000 --bin-width 50
```

## Dependencies

- `numpy` / `scipy` — FFT and signal processing
- `sounddevice` — cross-platform audio I/O
- `soundfile` — audio file decoding
- `rich` — terminal UI with live multi-line updates
- `click` — CLI argument parsing

## Development

```bash
pip install -e ".[dev]"
pytest tests/
```

## License

MIT
