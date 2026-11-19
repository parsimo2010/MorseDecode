# Decoder accuracy and real-time benchmarks

The Northern Utah WebSDR evaluation reduced character edits from 109 to 8
on 402 labeled off-air characters. It includes the manual copy, receiver-noise
and handoff tests, and current Chrome timings. [Northern Utah field results](utah-websdr.md)

## Earlier optimization benchmarks

The terminal and web app use the same JavaScript decoder. The reference for
the historical tables below is [`6b2ba41`](https://github.com/parsimo2010/MorseDecode/commit/6b2ba41).

## Optimization priorities and outcomes

| Priority | Option | Decision |
| --- | --- | --- |
| 1 | [Weak signal and fading detection](https://github.com/parsimo2010/MorseDecode/issues/7) | Use a local keying threshold when the signal is isolated, off-frequency evidence for noise bursts, and phase-sensitive detection when the carrier supports it. Short and long measurement windows cover fast and weak signals. |
| 2 | [Carrier tracking and interference](https://github.com/parsimo2010/MorseDecode/issues/8) | Follow a nearby spectral peak through drift. Favor strong keyed carriers during acquisition and retain the terminal's adjacent-channel guard. |
| 3 | [Ambiguous timing and spacing](https://github.com/parsimo2010/MorseDecode/issues/9) | Reject short, low-confidence pulses, estimate timing clusters when supported, and infer a dot cadence from recurring edges in weak, regularly keyed CW. Estimate extended letter spacing separately from keying speed. |
| 4 | [Compact language context](https://github.com/parsimo2010/MorseDecode/issues/1) | Tested a small list of CW abbreviations as a bounded prior. It changed at most two edits out of 2,057 validation characters across the two tested weights. The decoder uses timing and signal evidence alone. |
| 5 | [Real-time cost](https://github.com/parsimo2010/MorseDecode/issues/10) | Decimate with an anti-alias filter and find frequency quantiles by partitioning the samples. Keep the static browser build dependency-free. |

## Synthetic tests

Character error rate (CER) is the minimum number of insertions, deletions,
and substitutions divided by the reference character count. Spaces and all
characters in the printed prosign notation count. CER can exceed 100% when a
decoder outputs many extra characters. For SNR, the numerator is the RMS of
the nominal keyed tone before fading and the denominator is the RMS of the
generated audio noise. The band-limited cases use noise shaped around the
carrier with a nominal 500 Hz bandwidth.

The synthetic suite uses fixed seeds and includes QSO exchanges, prose, and
arbitrary code groups. Use `--holdout` for the separate validation messages
and noise seeds used during candidate selection.

| Validation condition | Before | After |
| --- | ---: | ---: |
| Clean | 0/121 | 0/121 |
| Clean, 46 WPM | 26/121 | 2/121 |
| +30 dB in 500 Hz shaped noise | 0/121 | 0/121 |
| +15 dB in 500 Hz shaped noise | 0/121 | 0/121 |
| +15 dB with QSB and variable keying | 94/121 | 43/121 |
| 0 dB in 500 Hz shaped noise | 19/121 | 7/121 |
| −6 dB in 500 Hz shaped noise | 136/121 | 35/121 |
| −12 dB white noise | 61/121 | 33/121 |
| −15 dB white noise | 384/121 | 105/121 |
| Fast CW in white noise | 49/121 | 72/121 |
| Carrier restarts its phase at each mark | 27/121 | 32/121 |
| 48 kHz capture with a strong out-of-band keyed tone | 0/121 | 0/121 |
| Deep QSB at +2 dB broadband SNR | 49/121 | 49/121 |
| Near steady tone | 0/121 | 0/121 |
| Near keyed station | 1/121 | 2/121 |
| Carrier drifts by 84 Hz | 64/121 | 15/121 |
| QRN crashes | 37/121 | 21/121 |
| Straight-key timing | 20/121 | 17/121 |
| Bug timing | 5/121 | 0/121 |
| Farnsworth spacing | 69/121 | 0/121 |
| Idle noise and steady tone | 0 insertions | 0 insertions |
| All validation conditions | 1,041/2,420 (43.0%) | 433/2,420 (17.9%) |

The older regression suite also checks speed changes, passband edges, exact
chunk-size parity, and fading without noise. On that suite, the −12 dB white
noise result improved from 43 to 18 errors per 103 reference characters and
the 10%-amplitude fade result improved from 81 to 2. The −18 dB white
noise case remains near the limit of intelligible output.

Fast, noisy CW and carriers that reset phase between marks gave mixed results
across the two splits. [Open measurements and follow-up](https://github.com/parsimo2010/MorseDecode/issues/11)

## Recorded audio

The recording benchmark uses the published W1AW audio and transcripts. It
downloads the source files to a local cache and scores the first labeled
excerpt. A second run applies repeatable fading and Gaussian noise to that
same audio. The recordings are machine-keyed practice material. The Utah
benchmark adds locally supplied off-air recordings. The field recording issue
tracks the public corpus.
[15 WPM archive](https://www.arrl.org/15-wpm-code-archive) · [20 WPM archive](https://www.arrl.org/20-wpm-code-archive) · [Field recording issue](https://github.com/parsimo2010/MorseDecode/issues/5)

| Recording | Before | After |
| --- | ---: | ---: |
| W1AW, 15 WPM, original | 5/139 | 0/139 |
| W1AW, 15 WPM, added fade and noise | 90/139 | 6/139 |
| W1AW, 20 WPM, original | 0/176 | 0/176 |
| W1AW, 20 WPM, added fade and noise | 80/176 | 10/176 |

## Repeat the benchmarks

```powershell
node tests/accuracy.mjs --baseline=6b2ba41
node tests/accuracy.mjs --holdout --baseline=6b2ba41
python tests/recordings.py --baseline 6b2ba41
node tests/realtime.mjs --baseline=6b2ba41
$chrome = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
node tests/realtime.mjs "--browser=$chrome"
```

Use Node.js 24. The recordings benchmark needs the project's Python
dependencies and Internet access for its first run. Pass `--match=...` to
filter the synthetic cases or `--verbose` to see their decoded text.

The real-time test feeds 20 ms blocks at 48 kHz and reports processing time
as a percentage of audio duration and per-block latency percentiles. With
Chrome it also runs the decoder from the bundled worker, then measures the
same bundled code on a page thread with DevTools set to a 6× CPU slowdown.
That setting serves as a proxy for slower hardware. Power use and physical
phone performance were outside this measurement.

These measurements came from an AMD Ryzen AI Max+ 395 running Windows.
The Node baseline used 6.3% of real time for a single default passband and
9.5% for the three guarded passbands.

| Runtime and workload | % of real time | p99 per 20 ms block |
| --- | ---: | ---: |
| Node, default passband | 0.9% | 1.12 ms |
| Node, three guarded passbands | 1.2% | 1.18 ms |
| Chrome worker, default passband | 0.9% | 1.10 ms |
| Chrome worker, weak CW | 1.0% | 1.40 ms |
| Chrome at 6× slowdown, default passband | 6.3% | 7.50 ms |
| Chrome at 6× slowdown, weak CW | 8.4% | 12.10 ms |
| Chrome at 6× slowdown, 100–3000 Hz | 42.8% | 35.00 ms |

The widest passband kept up on average in the throttled run and occasionally
took more than 20 ms to process a block. The worker can queue those blocks.
