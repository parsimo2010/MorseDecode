# Gqrx recordings from the attic EFHW

The 11 captures yielded 33 confirmed CW carriers. A count is per recording
and per carrier frequency. A station can appear at multiple frequencies or
in multiple recordings, and a frequency can carry both sides of a contact.
I checked the channel audio for Morse-length keying and repeated groups. The
capture times below use the filename dates and times as UTC.

| UTC, November 2026 | Tuned kHz | Mode and filter label | Length | CW carriers | Copy recovered |
| --- | ---: | --- | ---: | ---: | --- |
| 22 23:51:06 | 14030.500 | Receiver audio | 25 s | 1 | `BAND GONE HI CUAGN DE W1AW/7` |
| 22 23:51:37 | 14030.500 | Receiver audio | 12 s | 1 | `AW/7 W1AWX` with a clipped opening |
| 22 23:52:26 | 14030.700 | Receiver audio | 8 s | 1 | `K5AF?` |
| 22 23:52:35 | 14030.700 | Receiver audio | 45 s | 1 | `GUD CU NEW BAND HI 5NN WA` |
| 23 00:03:56 | 14029.600 | Receiver audio | 36 s | 1 | Partial call ending `GUV?` |
| 23 00:04:55 | 14030.500 | Receiver audio | 26 s | 1 | `JER CA` |
| 23 00:06:03 | 14122.600 | Receiver audio | 59 s | 0 | No confirmed CW |
| 23 00:08:41 | 14033.600 | IQ 80 kHz, AGC on | 167 s | 9 | NJ6Q, NB7O, N6CHU, KN6YKN, KI6OY and WA6MOW, plus partial exchanges |
| 23 00:12:21 | 14026.400 | USB 39.9 kHz, AGC on | 156 s | 6 | KI6OY, NJ6Q, W7LHT, KN6YKN, N6CHU and WA6MOW |
| 23 00:16:14 | 14026.400 | USB 39.9 kHz, AGC off | 74 s | 5 | N6CHU, KI6OY, W7FV, NJ6Q, W7LHT, KN6YKN and WA6MOW |
| 23 00:18:27 | 14033.400 | IQ 80 kHz, AGC off | 122 s | 7 | N6CHU, NJ6Q, KN6YKN, NB7O, W7LHT, WA6MOW and a partial CQ near 14022 kHz |

The JSON report has each confirmed carrier's signed offset, estimated RF
frequency where known, chosen filter, 700 Hz output pitch and full machine
transcript. Machine copy includes noise and partial characters. The catalog
contains 58 excerpts checked against the keying, including repeated calls,
names, locations and exchanges. The partial CQ around 14022 kHz was real CW
with a weak or incomplete callsign. At 00:12:21, the +4173 Hz candidate
repeated the +4107 Hz carrier's marks at the same times. Other rejected peaks
had no readable CW or consistent Morse timing. For ordinary receiver audio,
the offset is the measured audio pitch and the catalog frequency is the
receiver tuning. [Machine transcripts](../benchmarks/cw/gqrx-decodes.json) · [Reviewed text and audio](../benchmarks/cw/corpus.json)

## Contest recording format

Use Gqrx's **I/Q recorder** and save the native complex float32 `.raw` file
with its original filename. In these captures, the two IQ WAVs yielded 9
and 7 carriers and the two USB WAVs yielded 6 and 5. The captures were
sequential with different activity and durations. The IQ advantage is
its ability to retain both sides of the tuned frequency and let you choose
the filters after recording. [Gqrx I/Q recorder and filename format](https://github.com/gqrx-sdr/gqrx/blob/master/src/applications/gqrx/mainwindow.cpp#L1528-L1573)

The four wideband files were 48 ksample/s WAVs. IQ retained a theoretical
48 kHz span centered at tuning, with noise power already rolling off beyond
about 16–18 kHz on each side. USB retained up to 24 kHz above tuning, with
similar roll-off beyond about 16–18 kHz. The nominal 80 and 39.9 kHz filter
labels describe the Gqrx settings. An IQ signal near +16.4 kHz and a USB
signal near +23.6 kHz both carried WA6MOW around 14050 kHz. Record native IQ
at an effective rate such as 150 ksample/s to cover an 80 kHz contest window
with room for filter roll-off. At that rate the 8 bytes per complex sample
use 4.32 GB per hour. [Gqrx native IQ recording path](https://github.com/gqrx-sdr/gqrx/blob/master/src/applications/gqrx/receiver.cpp#L1128-L1158)

Start with fixed receiver gain and enough headroom for strong stations.
The `-noagc` captures were quieter and still yielded useful CW. The
sequential recordings do not isolate the effect of AGC on weak-signal copy.

## Run the pipeline

From the checkout with Python and Node.js 24 installed:

```powershell
python -m pip install -e ".[wideband]"
python -m morse_decode.wideband "recordings/gqrx*.wav" --output decode-output --workers 4
python -m morse_decode.wideband "recordings/gqrx*.raw" --output contest-output --search-hz -40000 40000 --workers 4
```

Use a new output location for a repeat run. Each capture gets a directory
with `report.json` and an 8 kHz PCM WAV per spectral candidate. The scanner
uses overlapping FFT windows and compares peaks to the nearby spectrum.
The extractor frequency-shifts each candidate to baseband, resamples and
filters it, then remodulates it at 700 Hz for the shared CW decoder. On
USB, the audio pitch is the positive RF offset from the tuned frequency.
The pipeline assumes left is I and right is Q for IQ WAVs, and complex
float32 little-endian for native Gqrx IQ. Use `--mode` and `--tuned-hz` to
override WAV filename metadata. For native IQ, the filename supplies the
sample rate.

A spectral candidate can be a CW signal, interference, or leakage from a
nearby station. Use the audio and transcript to confirm the count. Use
`--search-hz` to limit the RF range relative to the center of an IQ recording.
`--min-db` controls the contrast needed to return a candidate. For signals
within 45 Hz of IQ center, use `--offset-hz` to extract them directly around
the SDR's DC spike. The default
extraction bandwidth is 220 Hz. A 130 Hz filter helped isolate several
signals in these files. Faster keying or broader drift can benefit from
the wider filter.

## Reproduce a benchmark channel

Use the capture file and extraction settings recorded in the catalog's
`channel` metadata. For example, this extracts the NJ6Q channel from the
first IQ recording:

```powershell
python -m morse_decode.wideband recordings/gqrx_20261123_000841_14033600-IQ-80k.wav --output reviewed --offset-hz=-3086.1 --filter-hz 220 --tone-hz 700
```

Use the catalog's `file` value for the generated full-duration mono WAV
when rebuilding the clips from originals. For this channel the filename
is `gqrx-20261123-000841-m30861.wav`. Its clip frame bounds refer to this
WAV. The bundled clips can be scored or exported directly. These are
development excerpts from reviewed CW, so their error rate measures
transcript accuracy on those passages. The report's counts describe the
separate search and review step. [Corpus commands](../benchmarks/cw/README.md)

On the 58 new excerpts, both the current shared decoder and `636f0ff`
made 28 character edits on 601 reference characters (4.66% CER).
The two runs each made 134 edits on 3,434 characters across all 126
corpus clips.
