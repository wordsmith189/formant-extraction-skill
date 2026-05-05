---
name: transcribe-bi
description: >
  Transcribe a bilingual interview recording in three logical passes:
  speaker diarization first, per-segment language identification second,
  and language-conditioned ASR third. Produces a Rev-style JSON
  transcript carrying both a `speaker` ID and a `language` tag on
  every monologue. Designed for two-language recordings (e.g. Spanish/
  English code-switching, Mandarin/English heritage interviews) where
  Whisper's language head must be re-set per chunk rather than
  hard-coded for the whole file. Use whenever the user asks to
  transcribe a bilingual recording, transcribe code-switched audio, or
  produce a per-language tagged Rev-style JSON.
---

# transcribe-bi — bilingual transcription + diarization + language ID

This is the bilingual sibling of `transcribe-en`. It runs three
**ordered** passes, in this order — diarization is run *before*
language ID so each speaker's voice prints stay intact across
language switches, and ASR is run *after* language ID so Whisper's
language token can be set correctly per segment.

```text
audio
  │
  ├─ Pass 1: speaker diarization        (ECAPA-TDNN + agglomerative)
  │     ↓ per-segment speaker label
  ├─ Pass 2: language identification    (faster-whisper detect_language
  │     ↓ per-segment language tag       restricted to L1 / L2)
  └─ Pass 3: language-conditioned ASR   (faster-whisper transcribe with
        ↓                                  language=L1 or L2 per segment)
        Rev-style JSON with both speaker and language tags
```

The output of pass 3 is what `align-bi` consumes.

## When to use this skill instead of `transcribe-en`

- The recording has more than one language. Even if one of the two is
  English, do **not** use `transcribe-en` — it hard-codes
  `language="en"` and will mis-transcribe non-English stretches.
- The user has told the meta-skill `--mode bilingual` (or answered
  "Bilingual" to the monolingual / bilingual question at the top of
  `/formant-extraction`).

If only one language is present, use `transcribe-en` — it is faster
and its English-only Whisper invocation is more accurate on
monolingual American English than the language-conditioned path here.

## Output

`<basename>.JSON` (uppercase to match the Rev convention) placed beside
the input audio. Schema extends the `transcribe-en` schema with two
new fields:

```json
{
  "speaker_map": {"<id>": "<role>"},
  "selected_speaker": "<id>",
  "languages": {
    "L1": {"label": "English",  "whisper_code": "en", "webmaus_code": "eng-US"},
    "L2": {"label": "Spanish",  "whisper_code": "es", "webmaus_code": "spa-MX"}
  },
  "monologues": [
    {
      "speaker": <id>,
      "language": "L1",          // "L1" | "L2" — points into `languages`
      "elements": [
        {"type": "text",  "value": "word", "ts": 1.234, "end_ts": 1.456, "confidence": 0.97},
        {"type": "punct", "value": " "},
        ...
      ]
    }
  ]
}
```

`languages` is the answer the user gave to the two language questions
in the meta-skill. The `whisper_code` is what faster-whisper accepts
in `transcribe(..., language=...)`. The `webmaus_code` is what
`align-bi` will pass to BAS WebMAUS as `LANGUAGE=...`.

`monologues[].language` is set during pass 2 from Whisper's
`detect_language()` posterior, restricted to `{L1, L2}` (i.e. picked
as whichever of the two has higher probability — never a third
language). This keeps language drift inside the user-declared pair.

Roles in `speaker_map` are the same as in `transcribe-en`:
`"interviewer"`, `"participant"`, `"extra speaker"`.

## Inputs

| Argument | Notes |
|----------|-------|
| `--audio <path>` | Input recording. Any format ffprobe reads. |
| `--out <path>`   | Output Rev-style JSON. |
| `--n-speakers N` | Same as `transcribe-en`. Default 3. |
| `--l1-whisper <code>` | ISO 639-1 code for L1 (e.g. `en`, `es`, `zh`, `ru`). |
| `--l2-whisper <code>` | ISO 639-1 code for L2. |
| `--l1-label <text>`  | Display label, e.g. `"English"`, `"Spanish (Mexican)"`. |
| `--l2-label <text>`  | Display label. |
| `--l1-webmaus <code>` | WebMAUS language code for downstream `align-bi`. Defaults via the lookup table below. |
| `--l2-webmaus <code>` | WebMAUS language code. |
| `--model SIZE`        | `large-v3` recommended (its multilingual head is stronger than `large-v3-turbo`'s; the turbo distillation drops some non-English quality). Default `large-v3`. |

### Default language-code lookup

The four buttons in the meta-skill map to these defaults. The user can
override any of them via `--l*-whisper` / `--l*-webmaus` if their
recording is in a regiolect or sociolect that needs a different model
(e.g. `cmn-Hans-CN` for simplified-character Mandarin, `spa-ES` for
Iberian Spanish).

| Button label                | Whisper code | WebMAUS code |
|-----------------------------|--------------|--------------|
| (fairly standard) English   | `en`         | `eng-US`     |
| (fairly standard) Mandarin  | `zh`         | `cmn-CN`     |
| (fairly standard) Spanish   | `es`         | `spa-MX`     |
| (fairly standard) Russian   | `ru`         | `rus-RU`     |
| Other (free text)           | ask the user | ask the user |

For "Other," prompt the user for the ISO 639-1 (or 639-3) code. If
they don't know it, look it up against the BAS WebMAUS language list
(`https://clarin.phonetik.uni-muenchen.de/BASWebServices/services`)
and the Whisper supported-languages list. If WebMAUS does not support
the requested language, abort before running pass 1 with a clear
error — there is no point transcribing audio that the bilingual
aligner cannot handle downstream.

## Prerequisites

Same as `transcribe-en` (faster-whisper, SpeechBrain, scikit-learn,
torchaudio, ffmpeg, numpy). No new packages.

## Pass 1 — Speaker diarization

Run **diarization first**, on the full recording, and freeze the
per-segment speaker labels before language ID touches anything.
Reasoning: ECAPA-TDNN is robust to language changes within a single
speaker (the embedding captures voice quality and timbre, not
phonemic content), so doing diarization first gives stable speaker IDs
even when the speaker switches languages mid-utterance. Doing
language ID first risks splitting one speaker into two clusters
because their two languages produce slightly different segmentations.

Implementation matches `transcribe-en` pass 1:

1. ffprobe duration check; if > 20 min, split via `ffmpeg -c copy`
   into ≤ 20-min chunks. Diarization runs on the **full** audio
   (concatenated back) so cluster IDs stay consistent.
2. faster-whisper transcribes each chunk with word-level timestamps
   **using `language=None` (auto-detect)** — this pass exists only to
   get segment boundaries. The text is not used; pass 3 retranscribes
   each segment with a known language.
3. ECAPA-TDNN embeddings per Whisper segment of duration ≥ 0.5 s.
4. `AgglomerativeClustering(n_clusters=N, metric="cosine",
   linkage="average")` on L2-normalized embeddings.
5. Role heuristic (cluster dominating first 60 s → interviewer; rest
   ranked by total speech time).

Output of pass 1 is a list of segments tagged with `speaker_id` and
`(start, end)` on the original-recording timeline. The text from this
pass is discarded.

## Pass 2 — Language identification

For each segment, run faster-whisper's `detect_language()` on the
audio span:

```python
audio_seg = waveform[int(start*sr):int(end*sr)]
features = whisper.feature_extractor(audio_seg)
language, probs = whisper.detect_language(features)
```

`detect_language()` returns posterior probabilities over Whisper's
99 supported languages. We do not let it pick freely — instead we
**restrict the choice to {L1, L2}** by reading `probs[L1_code]` and
`probs[L2_code]` and tagging the segment with whichever is larger.
This prevents Whisper from drifting into a third language on a noisy
or short segment.

Edge cases:

- **Very short segments (< 0.5 s).** Inherit the language tag of the
  previous segment from the same speaker.
- **Both probabilities very low** (`max(p_L1, p_L2) < 0.3`). Tag as
  the more common language for that speaker so far in the recording,
  and surface a warning in the summary so the user knows to check the
  JSON before alignment.
- **Mid-segment code-switch.** Whisper's segmentation is sentence-
  level, so a single-word switch ("she said *vámonos* and we left")
  will land inside one segment and be tagged as a single language.
  This is a known limitation; the pipeline does not attempt sub-
  segment language splits.

## Pass 3 — Language-conditioned ASR

For each segment, run faster-whisper a second time with the language
fixed to the segment's tag:

```python
result, _ = whisper.transcribe(
    audio_seg,
    language=segment.language,    # "en" / "es" / "zh" / "ru" / etc.
    word_timestamps=True,
    beam_size=5,
)
```

Stitch all segments back into a Rev-style JSON. Each `monologue` is
defined as a maximal run of consecutive segments with the **same
`(speaker_id, language)`** pair — so a speaker who switches from
English to Spanish mid-turn produces two adjacent monologues, not
one. This makes the downstream chunking in `align-bi` a clean
per-language operation.

Word-level timestamps from pass 3 replace those from pass 1.
`confidence` is taken from Whisper's word-level probability.

## Stage 4 — Speaker selection + voice-type (HITL)

Identical to `transcribe-en` stage 2. The only addition is a per-
language readout in the cluster summary so the user can see, e.g.:

    Cluster 2 (heuristic guess: participant)
      total speech: 14m 22s
      first-60s share: 18 %
      language mix: L1 (English) 58 %  /  L2 (Spanish) 42 %
      sample turns:
        "And then we moved to Brownsville…"
        "…porque mis abuelos no hablaban inglés."

Show this for every cluster, then ask the same two questions as the
English pipeline — speaker ID and voice type (`low` / `high`).

With `--no-confirm`, take the heuristic guess for speaker and `low`
for voice type, surfacing both in the summary.

## Stage 5 — Filter to one speaker

Reuse `transcribe-en/scripts/filter_speaker.py`. The filter operates
on `monologues[].speaker` and is language-agnostic — the new
`language` field on each monologue rides through unchanged.

```bash
python3 ~/.claude/skills/transcribe-en/scripts/filter_speaker.py \
    --in  <basename>_full.JSON \
    --speaker <id> \
    --out <basename>.JSON
```

## Known limitations

- **Whisper sub-segment switches.** As noted above, a single-word
  insertion in the other language inside a longer monologue is tagged
  as the surrounding language. For projects that need fine-grained
  code-switch boundaries, plan a manual review at gate 1.
- **Diarization on bilingual speakers.** The same ECAPA-TDNN
  limitation that affects `transcribe-en` (embeddings averaged across
  speaker-boundary-spanning Whisper segments) applies here.
  Diarization quality typically holds up across language switches in
  one speaker, but mixed-segment failures look the same as in the
  monolingual pipeline. The lopsided-cluster check in stage 4 catches
  the worst cases.
- **Language coverage.** WebMAUS supports ~70 languages but Whisper
  supports 99 — a few languages can be transcribed but not aligned.
  The meta-skill checks both lists at language-selection time and
  refuses pairs that aren't supported by both.

## Citations

Same as `transcribe-en` (Whisper, faster-whisper / CTranslate2,
SpeechBrain ECAPA-TDNN). The bilingual variant adds no new
third-party tools.
