# Blind CW transcription audit

Two fresh-context LLM readers received 145 anonymous mono WAVs. Each developed its own offline signal analysis and froze a literal transcript before either reader saw the other copy or the catalog. They could inspect both ends of a clip, change the demodulation bandwidth, measure carrier phase and strength, and compare the timing of every mark and space. The coordinator then compared both copies with the catalog and used the source audio to adjudicate differences. The streaming decoder had no role in proposing these references. [Reusable review skill](../../../.agents/skills/review-cw/SKILL.md)

Both readers matched the previous catalog on 116 excerpts after normalization of prosigns. Acoustic adjudication retained 24 other references and corrected five. Two examples show why the distinction matters. Both readers initially copied `HEE`, but five distinct dits beginning at 6.096, 6.174, 6.252, 6.330 and 6.410 s confirmed the existing `5EE`. In another clip both readers omitted the final R in `AR`. Inspection of the full channel placed the R 0.26 s beyond the crop, so the corrected reference ends in A. [Per-clip decisions and frozen reads](clip-audit.jsonl) · [Time-aligned evidence](clip-evidence.jsonl.gz)

## Original recordings

The search covered all 22 original files, totaling 43 min 34 s. It examined 191 candidate frequency tracks, including 101 in the native IQ capture. Overlapping 16 s windows advanced by 8 s. Short retries used windows of up to 6 s at 2.5 s intervals with different amplitude gates. The archive contains 3,789 long windows and 58,112 nonempty short-window hypotheses. A search peak can also come from interference, a digital mode or receiver noise. The 14.1226 MHz recording yielded no verified CW. [Capture hashes, frequencies and coverage](source-coverage.json) · [Full tentative copies](source-attempts.jsonl.gz)

The readers examined 98 proposed intervals, including eleven detailed retries from the DC bulletin. Ninety intervals contributed 91 scored excerpts and 790 characters. One long interval supplied two clips separated by an uncertain procedural signal. Five other proposals overlap passages reviewed with more surrounding audio. Three further proposals remain unscored. The source readers' full attempts, including their disagreements on those passages, are preserved. The 91 new excerpts comprise 64 Gqrx, 14 Utah WebSDR, 11 DC WebSDR and two Texas WebSDR clips. [Candidate reads, decisions and scored frame ranges](source-candidates.jsonl) · [Boundary and mark evidence](candidate-evidence.jsonl.gz)

The new references preserve unusual sending. The five repetitions of `CQ` in one native IQ clip have about 193 ms between every character, so the literal reference is `CQCQCQCQCQ`. A weaker caller can be copied as `KE9AJC` from two repetitions. The DC group `024,` was uncertain even after two blind reads. Another receiver captured the same bulletin passage with clearly keyed digits. The envelopes stayed aligned through the following words, with correlations of 0.885 and 0.846 in successive five-second checks. Other DC passages, including `USING` and the N in `CHICHONI.`, have individual faded marks. Their evidence notes record where context contributed. LLM agreement and repeated transmissions supply different kinds of evidence. The notes identify which was available.

## Reading the data

The JSON Lines files use one JSON object per line. Open the compressed files with Python's `gzip.open(path, "rt", encoding="utf-8")`. A `#` in a blind or tentative read represents unresolved keying. An actual transmitted question mark is `?`. Reader copies retain their own spacing and prosign notation.

| File | Contents |
| --- | --- |
| `clip-audit.jsonl` | Each earlier clip's ID, PCM hash, two frozen readings and scored reference. Changed references include the previous text. |
| `clip-evidence.jsonl.gz` | First-pass carrier and dit estimates, measured mark intervals in milliseconds from the clip start, and the second reader's filter trials and assessment. |
| `source-coverage.json` | Original filenames, hashes, durations, number of spectral peaks and per-frequency attempt counts. Frequencies are signed capture offsets for IQ and audio frequencies for mono channels. |
| `source-attempts.jsonl.gz` | One row per frequency track. Each long window includes the start and end in source seconds and three gate settings' copies. Each short trial lists the start second, gate index and tentative copy. |
| `source-candidates.jsonl` | Two frozen readings, source interval and reason for a trim or exclusion. Published intervals include a catalog clip ID and exclusive end frame on the 8 kHz grid. |
| `candidate-evidence.jsonl.gz` | Source-aligned mark groups, surrounding gap measurements for proposed cuts, and clock-fit alternatives for the DC retries. |

The published corpus remains a development set. Its score describes selected excerpts. Estimating contest-wide recovery would also require an independently enumerated set of all transmitted stations and exchanges, including misses.
