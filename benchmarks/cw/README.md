# CW recording benchmark

Each WAV contains one reviewed passage. The catalog records its reference text, receiver, UTC time, tuned frequency, sample rate, source-file SHA-256, original sample bounds and clip PCM SHA-256. The 68 clips come from ten recordings and contain about 23 MB of mono 8 kHz, 16-bit PCM audio. The first 33 clips came from the Northern Utah WebSDR. [Catalog](corpus.json) · [WAV files](audio) · [Utah morning transcripts and exclusions](../../docs/utah-morning.md) · [Earlier Utah transcripts](../../docs/utah-websdr.md)

## W1AW bulletin and nearby interference

The November 20 batch includes two 7047.5 kHz W1AW bulletin recordings and one 7025.5 kHz conversation. The original downloads identify the NA5B receiver in the Washington DC area and the W2DB receiver in Crowley, Texas. The filenames supply UTC and tuned frequency. All three are in the development split.

In the Crowley bulletin, the same 49-character passage occurs twice. The bulletin tone is near 904 Hz. A second signal around 690 Hz intermittently overlaps the later passage. Both clips contain the original receiver audio. The reference for each is `PARTICIPATION IN THE CQ WORLD WIDE DX CW CONTEST.`

| Crowley source time | Benchmark excerpt |
| --- | --- |
| 29.70–59.16 s | [Earlier copy of the passage](audio/w2db-20261120-010928-237600.wav) |
| 171.03–191.30 s | [Nearby signal appears during the date group](audio/w2db-20261120-010928-1368240.wav) |
| 191.30–217.17 s | [Intermittent overlap during the bulletin](audio/w2db-20261120-010928-1530400.wav) |
| 217.17–246.90 s | [Repeated passage with the nearby signal](audio/w2db-20261120-010928-1737360.wav) |

The DC bulletin has a second interference example at 279.47–292.08 s. The reference is `ISLAND, IOTA OC DASH`. A tone fills the gaps during `DASH`. Changes in amplitude and phase at the 66.7 ms dit spacing distinguish the three dits of S and the four of H. The next identifier is partly masked, and scoring resumes at `BEGINNING NOVEMBER`. [DC interference clip](audio/na5b-20261120-010303-2235760.wav)

For the Crowley conversation, mark lengths and gaps support literal groups such as `2T17` and `5EE`. The clips omit the clipped opening word, an unclear exchange around 119–123 s and the unfinished final word. [All transcripts and exact sample bounds](corpus.json)

## Compare a decoder

Use the same Git revision of the corpus for both decoders. Start a fresh decoder for each clip, feed the WAV at its declared sample rate, flush at EOF and capture its final text. For comparison with MorseDecode, use a 400–1000 Hz passband, automatic pitch and speed, and chronological 20 ms blocks. Report any hints, manual tuning, preprocessing or offline lookahead used by the other decoder. The reference transcripts guided MorseDecode development.

If your decoder takes a WAV path and prints the transcript to standard output, run these commands from this directory. Substitute your executable and its arguments. The runner passes the absolute WAV path in place of `{wav}` and starts one process per clip.

```sh
python benchmark.py run predictions.jsonl my-decoder "{wav}"
python benchmark.py score predictions.jsonl
python benchmark.py score predictions.jsonl --json
```

For a GUI, web service or streaming API, produce UTF-8 JSON Lines with one entry per clip. Order is immaterial. Use an empty string for a decoder that heard nothing. Missing, extra or duplicated IDs fail validation.

```json
{"id":"utah-20261119-044453-0","text":"YOUR DECODER OUTPUT"}
```

The primary metric is the total Levenshtein edits divided by the total number of reference characters. Scoring uppercases text, collapses whitespace, and accepts `=` for `<BT>` and `+` for `<AR>`. Spaces, punctuation and the printed prosign characters count. A second metric ignores spaces and treats each prosign as one keyed symbol. This lets you distinguish spacing errors from errors in the letters themselves. The JSON report includes the corpus fingerprint, denominators and per-clip counts.

To generate predictions from this repository's shared decoder, run the following from the repository root.

```sh
python tests/recordings.py --utah --predictions predictions.jsonl
python benchmarks/cw/benchmark.py score predictions.jsonl
```

## Take the database elsewhere

Python 3.10 or newer is sufficient for the runner, scorer, exporter and importer. Run the export from this directory and choose a new destination.

```sh
python benchmark.py export ../cw-bundle
```

The bundle contains `audio/`, `corpus.json`, the standalone `benchmark.py`, an `inputs.jsonl` list of IDs and relative WAV paths, and `corpus.sqlite3`. Supply only the input list and WAVs to a decoder during blind testing. The SQLite database joins each clip to its source recording.

```sql
SELECT r.recorded_utc, c.audio, c.text,
       (c.end_frame - c.start_frame) * 1.0 / r.sample_rate AS seconds
FROM clips AS c JOIN recordings AS r ON r.id = c.recording_id
ORDER BY r.recorded_utc, c.start_frame;
```

## Add reviewed material

1. Keep the original mono 16-bit PCM WAV. Find boundaries in silence on either side of complete Morse groups. Split around doubtful passages. Preserve repeated letters, spelling, cut numbers and prosigns. Use `development` for recordings used to tune a decoder. Reserve `holdout` for independently labeled recordings set aside before tuning.
2. Write a UTF-8 review file like the example below. Replace the example values with the recording details and your copy. Frame numbers are zero-based with an exclusive end. At 8 kHz, `[8000, 24000)` covers exactly two seconds.
3. Run `python benchmark.py add original.wav review.json` in this directory. It checks the source format, computes both hashes, validates the intervals, extracts the WAVs and appends the recording to the catalog. Commit the catalog and new clips together. Existing records can be rebuilt with `python benchmark.py build PATH_TO_ORIGINAL_WAVS`.

```json
{
  "id": "receiver-20261120-120000",
  "source": "Receiver name",
  "recorded_utc": "2026-11-20T12:00:00Z",
  "frequency_khz": 7030.0,
  "usage": "holdout",
  "clips": [
    {"start_frame": 8000, "end_frame": 24000, "text": "CQ"}
  ]
}
```

The sample index and parent ID form the stable clip ID. Record a new Git revision and corpus fingerprint after any reference correction. MorseDecode's regression budgets are maintained separately in [field-limits.json](../../tests/fixtures/field-limits.json).
