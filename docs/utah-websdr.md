# First four Northern Utah WebSDR field recordings

At Git revision `3463ef4`, the shared JavaScript decoder made **8 character edits in 402 reference characters** on six labeled excerpts. The previous release made **109 edits** on the same samples. The excerpts cover 228.7 seconds of the 239.6 seconds recorded. These four recordings guided development. Their scores measure improvement on these operators and reception conditions.

The public corpus now also includes three morning recordings. [New transcripts and seven-recording comparison](utah-morning.md)

## Reading the recordings

I located carriers in spectrograms, mixed each carrier down to baseband, and examined its amplitude and phase through the keying. I measured the lengths of marks and spaces and compared the resulting Morse groups across several bandwidths and thresholds. For weak passages I also compared the waveform with timed dot-and-dash patterns. The pitch and speed estimates below describe the manual reading. The decoder received the original audio and its normal 400–1000 Hz search band.

Times are UTC on 2026-11-19. `<BT>` and `<AR>` represent single prosigns. The copy preserves cut numbers, unusual spellings and conspicuous pauses. Spaces within recognizable callsigns and signal reports are normalized in the reference. The bracketed notes below identify uncertain audio.

### 04:44:53 · 7031 kHz · 76.18 s

One carrier near 724 Hz, about 19 WPM. The weak middle letter in `VIN` has two dots. The antenna description and the numbers are clear through the end of the clip.

> FB VIN SLD CPY <BT> HERE RIG K3 RUNNING 90 W TO EDZ OF 270 FT WIRE CENTER FED WITH 450 LADDER LINE CENTER UP 50 FT <BT> USE ANT FOR 160 TO 30

### 04:46:40 · 7034 kHz · 39.55 s

The first operator is near 747 Hz at about 26 WPM. The opening sounds like the end of `…WAT`. The recording begins during a mark. `TIRENG` and `SOWL` are the letter groups I could trace. In context the latter reads as “SO WL.” The letters in `HW IT GOES` run close together.

> [clipped] VY TIRENG <BT> SOWL C S U HW IT GOES TMW <AR> NF7N K9UIY K

A weaker operator comes in near 833 Hz around 25.2 s. I can trace `-..` followed by `NF7N`, and then `NU STILL` around 32.2–35.5 s. Later I can pick out `IN`, but fades obscure enough marks to make a complete sentence unreliable.

> D NF7N [unclear] NU STILL [unclear] IN [cut off]

The scored intervals are 1.42–28.00 s and 32.12–35.86 s. The first includes the pitch change.

### 04:47:27 · 7031 kHz · 37.73 s

One carrier near 758 Hz at about 20 WPM. The opening gives `GE`. The sequence after the first `38` is `...--`, a long pause, `--..`, then `-.--`. The later pauses divide the word “insurance” into three groups.

> GE 67 67 ES HAM 38 3 ZY ALSO MOSTLY CW <BT> RETIRED IN SUR ANCE / FINANCIAL

### 04:49:04 · 7029 kHz · 86.11 s

K3PR is near 700 Hz at about 18 WPM. The clip begins with the final `Q` of a call. A weaker station answers near 584 Hz around 26.1 s at about 22 WPM. I can trace a `D` in the fade before `W2GLN`. The suffix and the repeated callsign can be checked against K3PR's acknowledgment. K3PR returns at about 44.6 s. The signal report is sent twice as `57N`.

> Q DE K3PR K3PR CQ DE K3PR K
>
> K3PR K3PR [unclear around D] W2GLN W2GLN K
>
> RR W2GLN DE K3PR GE TNX CALL UR 57N 57N QTH TRENTON , TX TRENT [cut off]

The scored intervals are 0–32.87 s and 34.37–85.94 s. Both include a station handoff. A mark begins near the very end of the file, after the last complete `T`.

## Accuracy

Each excerpt starts a fresh decoder and feeds 20 ms blocks in time order. The score counts insertions, deletions and substitutions, including spaces and printed prosign notation. There are no callsign hints or tuning instructions in the fixture input. Separate full-file runs exercised continuous decoding in Chrome.

| Start UTC | Reference characters | Previous edits | Updated edits |
| --- | ---: | ---: | ---: |
| 04:44:53 | 141 | 17 | 0 |
| 04:46:40 | 73 | 18 | 3 |
| 04:47:27 | 75 | 15 | 0 |
| 04:49:04 | 113 | 59 | 5 |
| **Total** | **402** | **109 (27.11% CER)** | **8 (1.99% CER)** |

Six remaining edits are spaces. The character substitutions are `STI7L` for `STILL` and `K3PA` for one repetition of `K3PR`. Uncertain stretches of the weak 7034 kHz reply are outside the score.

| Same excerpts under changed conditions | Previous edits | Updated edits |
| --- | ---: | ---: |
| 48 kHz resampling, gain ×0.23 | 113 | 8 |
| All audio pitches shifted up 83 Hz, gain ×0.58 | 110 | 9 |
| Receiver gain varied at 0.23 Hz | 110 | 17 |

The gain variation affects noise and signal together. The RF signal-to-noise ratio of the original recordings is unknown.

## Decoder changes and checks on other audio

The decoder checks the shape of the receiver noise across frequency. When a receiver filter removes noise from the edges of the search band, it measures noise alongside the carrier and compares ambiguous pulses at two bandwidths. It checks for phase consistency before accepting weak peaks in filtered noise. During acquisition it also measures the interval between successive rising edges, which helps when the receiver lengthens marks and shortens gaps.

When a station signs over, the decoder looks for a newly keyed carrier and resets the sender timing on a pitch change. It tests whether both carriers were previously transmitting at once, so a third station in a word space has less chance of taking over.

The new synthetic receiver cases also informed the detector settings. The W1AW comparison uses published transcripts.

| Test | Previous edits | Updated edits |
| --- | ---: | ---: |
| Earlier synthetic development cases | 353/2,400 | 353/2,400 |
| Earlier synthetic validation cases | 433/2,420 | 429/2,420 |
| New synthetic station replies, validation | 137/145 | 24/145 |
| Same exchanges with a third keyed station | 83/145 | 13/145 |
| Filtered receiver noise alone, validation | 375 insertions | 0 insertions |
| W1AW practice recordings, original | 0/315 | 0/315 |
| W1AW with added fading and noise | 16/315 | 16/315 |

The synthetic carrier-phase-reset case increased from 32 to 33 edits on 121 validation characters. The +15 dB variable-keying and fading case stayed at 43/121. A broader test of field accuracy needs recordings from more receivers and senders. [Field recording issue](https://github.com/parsimo2010/MorseDecode/issues/5)

Chrome resampled each complete WAV to 48 kHz and ran it through the bundled worker's start, audio and stop handlers. The worker used about 0.9% of playback time. With a 6× DevTools CPU slowdown on the page thread, the same decoder used 7.1–7.4% of playback time. The 99th-percentile processing time was at most 9.0 ms per 20 ms block. The measurements are from desktop Chrome on Windows with an AMD Ryzen AI Max+ 395. Physical phone performance has not been measured.

## Repeat the checks

The seven-recording benchmark now reads the committed WAV clips. The corpus records source and clip hashes and exact sample bounds. Full original WAVs in `recordings/` can also be replayed in the Chrome check below. [Portable field corpus](../benchmarks/cw/README.md)

```powershell
python tests/recordings.py --utah --baseline 5c33295 --verbose
python tests/recordings.py --utah --baseline 5c33295 --gain-fade
node tests/accuracy.mjs --match=receiver --holdout --baseline=5c33295 --check
python -m pytest
$chrome = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
$wavs = Get-ChildItem recordings -Filter *.wav | ForEach-Object { '--wav=' + $_.FullName }
node tests/realtime.mjs "--browser=$chrome" --verbose @wavs
```
