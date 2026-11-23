# CC0 hand-sent and off-air recordings

| Source | Reviewed source times | Scored copy | Keying and reception |
| --- | --- | --- | --- |
| US Department of Defense, *Technique of Hand Sending*, 1944 | 57.000–59.980 s, 60.940–64.400 s, 64.400–66.000 s | `GXYP`, `GLMYK`, `LJ` | Straight key demonstration, about 783 Hz and 20–22 WPM in the soundtrack |
| Mediaman57, *SOS-MorseCode.wav* | 0.500–7.200 s | `SOS SOS SOS` | MFJ paddle, close-miked to MiniDisc, pitch shifted from roughly 2.1 kHz to 702 Hz |
| ok1has, *S57LC-20120914-1105UTC-7013.31KHZ.wav* | 50.250–59.380 s | `PWR SUPPLY SEEMS` | Off-air loudspeaker recording, carrier chirp, about 22 WPM, pitch shifted +250 Hz |
| Same off-air passage with controlled static | 50.250–59.380 s | `PWR SUPPLY SEEMS` | Six reproducible broadband bursts model brief QRN crashes |

The three sources have a CC0 1.0 dedication. The original receiver or
recording filter bandwidths are undocumented. The raw off-air clip retains
its chirp and noise. The static variant uses a seeded noise overlay and the
same reference. [Defense Department film](https://archive.org/details/gov.dod.dimoc.23735) · [Paddle recording](https://freesound.org/people/Mediaman57/sounds/347147/) · [Off-air recording](https://freesound.org/people/ok1has/sounds/165450/) · [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)

## Blind review

Two independent readers examined four anonymous WAVs before the decoder
scored them. The times below refer to the anonymous inputs.

| Anonymous WAV prefix | Reader A | Reader B | Decision |
| --- | --- | --- | --- |
| `0687de0d` | `SOS SOS SOS` | `SOS SOS SOS` | Three complete groups between 0.35 and 6.37 s. Later repeats were outside the review window. |
| `32f8b52d` | `PWR SUPPLY SEEMS` | `PWR SUPPLY SEEMS` | Three complete groups from about 0.70 to 9.72 s. The M to S gap is about 132 ms versus 56 ms between elements. |
| `4f5586cb` | `GXYP[O?] GLMYKLJ` | `SNY GXYP[Z?] GLMYK LJ` | Score the agreed letters. Exclude the noisy opening and disputed O/Z at 5.05–5.72 s. Split the last passage at the uncertain space. The K to L gap is about 240 ms, compared with 124–182 ms between nearby letters and 273 ms in the preceding group pause. |
| `ca64c675` | `HOW CHARLI[E?]` | `[M/K?]OW [?][H?] ARLI [?]` | Leave film time 39–46 s unscored. The readers found common letters amid swept interference but disagreed on complete groups. |

## Reproduce and score

The source inputs are the Archive.org 512 kb/s MP4 and the Freesound HQ
MP3 previews. The source SHA-256 values below pin the inputs to the
reviewed copies. The catalog separately pins the prepared WAVs and extracted
clip PCM. Preparation used FFmpeg 9.0.2, then SciPy's analytic signal to
translate the two Freesound excerpts into the decoder's default passband.
Only the labeled WAV excerpts are bundled.

| Download | SHA-256 |
| --- | --- |
| [`hand.mp4`](https://archive.org/download/gov.dod.dimoc.23735/gov.dod.dimoc.23735_512kb.mp4) | `566532031e866aeed4a0f448492a20ab51f3ee296d952379cd8ed4848228b027` |
| [`347147.mp3`](https://cdn.freesound.org/previews/347/347147_5501146-hq.mp3) | `42ebc1ebd37574aaf4c57185033fce2a7ce1a998c5f6307d9f5f7426fe8e4907` |
| [`165450.mp3`](https://cdn.freesound.org/previews/165/165450_108524-hq.mp3) | `0b5dc9917eb0bed7f3f829d993f8083c00e2ab81476ee1562dca83e5815c94f2` |

```sh
python benchmarks/cw/prepare_public_audio.py originals --hand hand.mp4 --paddle 347147.mp3 --offair 165450.mp3
python tests/recordings.py --utah --predictions predictions.jsonl
python benchmarks/cw/benchmark.py score predictions.jsonl --groups
```

The reference decoder at `5ac5262` copied the three straight-key passages,
the off-air passage and its static variant verbatim (43 characters). Its
paddle copy had 10 edits across 11 characters. Existing QRM and QSB labels
identify the overlapping bulletin tones and faded marks from the
[field review](review/README.md).
