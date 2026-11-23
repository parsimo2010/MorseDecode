# Decoder accuracy and real-time benchmarks

## Fast CW and carrier phase resets

A shorter window preserves fast elements once the decoder has learned the
dit length and measured enough signal contrast. When a noisy carrier has
enough contrast to be read from magnitude alone, a coarse phase estimate
must show stronger coherence before it can override that magnitude.
The receiver's weak-signal path retains its original coherent integration.

| Condition | Four validation seeds, baseline → current | Fresh messages, baseline → current |
| --- | ---: | ---: |
| 38 WPM, −10 dB white noise | 192 → 190 / 484 | 36 → 33 / 101 |
| Random phase restart on each mark | 139 → 99 / 484 | 19 → 15 / 101 |
| 38 WPM with random phase restarts | 155 → 109 / 484 | 32 → 24 / 101 |
| Alternating 180° phase on successive marks | 86 → 81 / 484 | 20 → 16 / 101 |
| −15 dB white noise | 200 → 200 / 484 | 29 → 29 / 101 |
| Clean, including 46 WPM | 0 → 0 / 968 | 0 → 0 / 202 |

The alternating-phase case gained three edits on seed 7121 and improved
across the pooled seeds. The more aggressive short-window candidate and
multi-window energy candidates traded gains for regressions in deep noise
or mixed fading. The selected decoder matched the `f4a82d1` score of
206 edits across 4,488 characters on all 242 field excerpts and preserved
every clip's regression budget. On this Windows machine the Node decoder's
95th-percentile time per 20 ms block was 1.41 ms on the default passband
and 4.90 ms on the wide passband, compared with 1.48 and 4.95 ms before.

```powershell
foreach ($seed in 7121, 20261123, 405731, 93941) {
  node tests/accuracy.mjs --holdout "--seed=$seed" --baseline=f4a82d1 --check
}
node tests/accuracy.mjs --fresh --baseline=f4a82d1
python tests/recordings.py --utah --baseline f4a82d1
node tests/realtime.mjs --baseline=f4a82d1
```

## Blind-reviewed corpus and difficult source excerpts

Two independent readers transcribed the 145 existing clips before seeing their
labels. Acoustic review corrected five references. A search of all 22 original
recordings added 91 scored excerpts, including weak stations and incomplete
contacts. Revisions `f5f635e` and `05dcbaa` used the same 236 WAVs, corrected labels, default
400–1000 Hz search band and a fresh decoder per clip. Accuracy is one minus
character error rate, including word spaces, punctuation and prosigns.
[Audit, independent reads and source coverage](../benchmarks/cw/review/README.md)

| Field audio | Clips | Characters | Edits at `f5f635e` | Edits at `05dcbaa` | Accuracy before → after |
| --- | ---: | ---: | ---: | ---: | ---: |
| Earlier clips, reviewed labels | 145 | 3,644 | 140 | 116 | 96.2% → 96.8% |
| Newly scored excerpts | 91 | 790 | 134 | 80 | 83.0% → 89.9% |
| **Entire corpus** | **236** | **4,434** | **274** | **196** | **93.8% → 95.6%** |
| Native 40 m IQ | 33 | 323 | 36 | 15 | 88.9% → 95.4% |
| Other Gqrx captures | 108 | 1,039 | 94 | 58 | 91.0% → 94.4% |
| DC bulletin | 24 | 446 | 75 | 54 | 83.2% → 87.9% |
| Texas recordings | 24 | 1,058 | 30 | 32 | 97.2% → 97.0% |
| Utah recordings | 47 | 1,568 | 39 | 37 | 97.5% → 97.6% |

Of the 236 clips, 34 improved, 195 kept their score and seven regressed.
The decoder copied 147 verbatim. The public scorer counted 75 keyed-symbol
edits across 3,515 symbols. The scored corpus fingerprint is
`ca5985402735fb51a18f1b2ac461f99799ca990a1e19562b774d47ba9071b2ec`.
The 14 new native IQ excerpts improved from 19
edits to three on 114 characters. The 11 newly recovered DC excerpts improved
from 39 to 32 on 126 characters. With an artificial gain fade over all 236 WAVs,
edits fell from 392 to 313 (91.2% to 92.9% accuracy). On the independent W1AW
15 and 20 WPM reference passages both versions copied all 315 characters, or
311 of 315 with added noise and fading.

The streaming detector now estimates local carrier phase inside a narrow
receiver filter and uses the perpendicular component to measure noise. When
neighboring frequencies show a common change in gain it adjusts the samples
before measuring phase. A regular keying clock can recover a mark obscured by
interference. A measured clock on a weak coherent carrier can bridge a fade
for up to 1.2 seconds. The timing estimator also learns stretched letter gaps
from the sender before a clear word space arrives.

| Controlled signal condition | Accuracy at `f5f635e` | Accuracy at `05dcbaa` |
| --- | ---: | ---: |
| Clean 23 or 46 WPM | 100% | 100% |
| Uneven Farnsworth spacing | 74.7% | 97.0% |
| Straight key | 91.7% | 91.7% |
| Narrow receiver, 0 dB in its passband | 33.6% | 69.4% |
| Same receiver, changing output gain | 9.6% | 69.4% |
| −6 dB in 500 Hz noise | 89.5% | 90.4% |
| −12 dB broadband white noise | 87.9% | 90.9% |
| −15 dB broadband white noise | 49.0% | 54.8% |
| 38 WPM, −10 dB broadband white noise | 51.5% | 59.0% |
| Deep signal fading | 66.4% | 66.4% |

These rates pool four validation messages across seeds 7121, 20261123 and
405731. The last seed was first scored after selecting the carrier and
timing changes. Each row
has 363 reference characters per condition. The three cold-start idle controls
produced zero characters across all seeds. Across all validation conditions
there were 1,659 edits before and 1,161 after on 9,654 reference characters.

Separate tests appended receiver noise after 60 weak transmissions. Requiring
carrier energy over most of a dit when copy resumes after a long gap reduced
the additional edits from 223 to 82, compared with the same decoder without
that check. Across 204 trials with genuine weak terminal groups and gaps up to
1.9 s, the check preserved all 91 previously correct endings and recovered one.

The field corpus has repeated senders, uncalibrated SNR and deliberately
selected excerpts. Its score measures copy on
those excerpts. Contest-wide station or exchange recovery requires a separately
labeled complete capture.

On this Windows machine, Chrome's decoder worker took 1.2 ms and 1.4 ms at
the 95th percentile per 20 ms block on the new native IQ `KE9AJC` clip and
the weak DC `IN THE CQ WORLD` excerpt, respectively. The default 48 kHz passband
took 1.4 ms and the wide 100–3000 Hz passband took 4.6 ms. The wide passband
exceeded the block duration with Chrome's simulated 6× CPU slowdown.

```powershell
python tests/recordings.py --utah --baseline f5f635e
python tests/recordings.py --utah --gain-fade --baseline f5f635e
python tests/recordings.py --baseline f5f635e
foreach ($seed in 7121, 20261123, 405731) {
  node tests/accuracy.mjs --holdout "--seed=$seed" --baseline=f5f635e
}
node tests/realtime.mjs --baseline=f5f635e
$chrome = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
node tests/realtime.mjs "--browser=$chrome" `
  --wav=benchmarks/cw/audio/gqrx-20261123-014653-m295169-1526536.wav `
  --wav=benchmarks/cw/audio/na5b-20261120-010303-1667120.wav
```

## Earlier Gqrx and WebSDR evaluation

From `561bc5e` to `f5f635e`, the shared streaming decoder reduced character edits
from **166 to 145** across the 145 then-available off-air clips. To reproduce
this comparison with the original labels, run the commands below from a
checkout of `f5f635e`. Eleven clips improved, six regressed and
128 kept their previous score. Both decoders started fresh on each WAV with
the default 400–1000 Hz passband and no speed, pitch or transcript hints.
Accuracy below means one minus character error rate and includes spaces,
punctuation and printed prosigns. [Recordings and scoring](../benchmarks/cw/README.md)

| Off-air recordings | Clips | Characters | Previous edits | New edits | New accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| Gqrx native 40 m IQ | 19 | 209 | 32 | 17 | 91.9% |
| Other Gqrx captures | 58 | 601 | 28 | 27 | 95.5% |
| DC W1AW bulletin | 13 | 320 | 45 | 36 | 88.8% |
| Texas W1AW bulletin | 10 | 431 | 2 | 2 | 99.5% |
| Texas conversation | 12 | 606 | 28 | 28 | 95.4% |
| Utah recordings | 33 | 1,476 | 31 | 35 | 97.6% |
| **All recordings** | **145** | **3,643** | **166** | **145** | **96.0%** |

These are development recordings. The Gqrx references were reviewed with
decoder assistance and cover selected excerpts from isolated channels. The
40 m accuracy therefore measures copy on those excerpts. Measuring the
fraction of contest contacts recovered would also require independent labels
for stations and exchanges across an entire capture.

With a repeatable gain fade applied to all 145 WAVs, edits fell from 222 to
219. On the two archived 15 and 20 WPM W1AW practice excerpts, both decoders
copied all 315 characters correctly. Adding fade and noise to those same
excerpts reduced accuracy to 94.9% on the previous decoder and 98.7% on
the new one.

### Measured accuracy by signal condition

The table pools the four synthetic validation messages across three starting
seeds (`7121`, `20261123`, `915907`). Each ordinary condition has 363
reference characters. Receiver exchanges have 435 because they include a
reply. The messages repeat across seeds, so the rates describe sensitivity
to noise and keying variation within these fixtures. The final seed was run
after the decoder changes were fixed. Field recordings have no calibrated
SNR labels. See the synthetic tests below for the noise bandwidth convention.

| Synthetic condition | Previous accuracy | New accuracy |
| --- | ---: | ---: |
| Clean at 23 or 46 WPM, or +15 / +30 dB in 500 Hz noise | 100% | 100% |
| 0 dB in 500 Hz noise | 96.1% | 95.9% |
| −6 dB in 500 Hz noise | 74.4% | 88.4% |
| −12 dB broadband white noise | 75.5% | 89.5% |
| −15 dB broadband white noise | 11.3% | 53.7% |
| 38 WPM in −10 dB broadband white noise | 46.6% | 48.5% |
| +15 dB with fading and variable keying | 63.6% | 79.1% |
| Deep fading at +2 dB broadband SNR | 60.3% | 64.7% |
| Receiver AGC with fast selective fading | 74.9% | 87.1% |
| Straight key | 92.6% | 92.6% |
| Bug or Farnsworth spacing | 100% | 100% |
| Carrier drift | 87.9% | 89.5% |
| Impulsive static | 89.8% | 89.3% |
| **All synthetic validation conditions** | **83.8%** | **88.4%** |

The pooled totals were 1,385 and 991 edits on 8,565 characters. Both
decoders produced zero insertions on both idle controls across all three
seeds. At −18 dB broadband SNR the separate regression suite still had
92 edits on 103 characters with the new decoder.

### What changed and what it costs

On a weak carrier that holds phase, the decoder measures energy along the
carrier phase and uses the perpendicular component to estimate noise.
When rising and falling edges maintain a dit clock across three sections
of recent audio, it sums the evidence inside each dit and compares silence,
dit and dah sequences. An isolated carrier with fading can use a local
amplitude threshold. At startup the decoder keeps early groups in the
preview longer, giving later marks a chance to resolve the sending speed.
It also uses onset-to-onset timing in noisy audio and accounts for long
letter gaps from operators who send unusually long dahs.

On the same Windows machine with Node 24, default-passband processing used
0.9% of real time on both revisions. Weak CW rose from 1.0% to 1.3%.
Its 99th-percentile processing time per 20 ms block rose from 1.43 to
2.09 ms. The Chrome worker measured 2.00 ms for weak CW and 1.10 ms for
the DC interference excerpt at the 99th percentile.

```powershell
python tests/recordings.py --utah --baseline 561bc5e
python tests/recordings.py --utah --gain-fade --baseline 561bc5e
python tests/recordings.py --baseline 561bc5e
foreach ($seed in 7121, 20261123, 915907) {
  node tests/accuracy.mjs --holdout "--seed=$seed" --baseline=561bc5e
}
node tests/realtime.mjs --baseline=561bc5e
```

## Earlier Utah evaluation

The Northern Utah WebSDR evaluation reduced character edits from 109 to 8
on 402 labeled off-air characters. It includes the manual copy, receiver-noise
and handoff tests, and Chrome timings from that revision. [Northern Utah field results](utah-websdr.md)

## DC and Texas WebSDR recordings

The 35 reviewed clips from three recordings were used to develop weak-mark
recovery. When the sender maintains a steady cadence, the decoder can check
the middle of a predicted dit for energy at the carrier frequency. This
recovers some marks that fall below the usual threshold during a fade.
The table compares `636f0ff` against the decoder at `64793a7` on
the same labeled WAVs. [Recordings and scoring](../benchmarks/cw/README.md)

| Recording | Clips | Reference characters | Before | After |
| --- | ---: | ---: | ---: | ---: |
| DC W1AW bulletin | 13 | 320 | 55 | 45 |
| Texas W1AW bulletin | 10 | 431 | 2 | 2 |
| Texas conversation | 12 | 606 | 28 | 28 |
| Earlier Utah recordings | 33 | 1,476 | 31 | 31 |
| Total | 68 | 2,833 | 116 | 106 |

Five DC clips improved, including the nearby-tone excerpt labeled
`ISLAND, IOTA OC DASH`, which went from nine edits to seven. Every other
clip kept its previous score. With the gain-fade test enabled, all 68 clips
matched their previous scores (140 edits). Scores also matched per example
on both synthetic suites and on the two archived W1AW excerpts tested
with and without added fade and noise.

On the DC nearby-tone clip, the Chrome worker took 1.0 ms at the 95th
percentile per 20 ms audio block (1.4 ms at the 99th percentile). In the
Node real-time test, default-passband processing used 0.9% of real time on
both revisions, and weak CW used 1.0% on both.

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
same audio. The recordings in the historical table below are machine-keyed
practice material. The separate seven-recording Utah comparison
reduced field edits from 55 to 31 on 1,476 characters. The current full-corpus
comparison is at the top of this document.
[Public corpus](../benchmarks/cw/README.md) · [Field results](utah-morning.md)
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
