---
name: transcribe-en
description: >
  Transcribe a monolingual American English interview recording with
  word-level timestamps and speaker diarization, then guide the user
  through picking which speaker (typically the participant) to feed into
  alignment and vowel extraction. Produces a Rev-style JSON transcript
  containing only the chosen speaker. Uses faster-whisper for ASR (CTranslate2
  runtime, cross-platform), SpeechBrain ECAPA-TDNN embeddings for speaker
  identity, and agglomerative clustering for diarization. Use whenever the
  user asks to transcribe an English interview, diarize a recording, or
  produce a Rev-style JSON transcript.
---

# transcribe-en — English transcription + diarization + speaker selection

Three logical stages, run in order:

1. **Transcribe + diarize** the full recording (`transcribe_diarize.py`)
   into an unfiltered Rev-style JSON containing every speaker's turns.
   Each turn carries a numeric speaker ID; a heuristic guesses which ID
   is the interviewer vs. participant.
2. **Confirm the speaker pick** with the user (interactive — Claude
   reads the JSON, shows the heuristic's guess plus a sample turn or
   two from each speaker, and asks the user to confirm or swap).
3. **Filter** the JSON to that one speaker (`filter_speaker.py`).

The output of stage 3 is what `align-en` consumes.

## Output

`<basename>.JSON` (uppercase to match the Rev convention) placed beside
the input audio. Schema:

```json
{
  "speaker_map": {"<id>": "<role>"},
  "selected_speaker": "<id>",
  "monologues": [
    {
      "speaker": <id>,
      "elements": [
        {"type": "text", "value": "word", "ts": 1.234, "end_ts": 1.456, "confidence": 0.97},
        {"type": "punct", "value": " "},
        ...
      ]
    }
  ]
}
```

`speaker_map` keeps every speaker the diarizer found, so the file
remains a complete record of who's in the recording. `selected_speaker`
records which one was chosen for downstream alignment;
`monologues` contains only that speaker's turns after stage 3.

Roles in `speaker_map` are one of: `"interviewer"`, `"participant"`,
`"extra speaker"`.

## Prerequisites

| Tool         | Check                                                         | Install |
|--------------|---------------------------------------------------------------|---------|
| faster-whisper | `python3 -c "import faster_whisper"`                       | `pip3 install faster-whisper` |
| SpeechBrain  | `python3 -c "from speechbrain.inference.speaker import SpeakerRecognition"` | `pip3 install speechbrain` |
| scikit-learn | `python3 -c "from sklearn.cluster import AgglomerativeClustering"` | `pip3 install scikit-learn` |
| torchaudio   | `python3 -c "import torchaudio"`                              | `pip3 install torchaudio` |
| ffmpeg + ffprobe | `which ffmpeg ffprobe`                                    | `brew install ffmpeg` |
| numpy        | `python3 -c "import numpy"`                                   | `pip3 install numpy` |

First run of `transcribe_diarize.py` downloads the Whisper model
(`large-v3-turbo` by default; ~1.5 GB) and the SpeechBrain ECAPA-TDNN
weights (~80 MB) and caches them under `/tmp` (see `--cache-dir` to
override).

## Inputs

One argument: the audio file (any format `ffprobe` reads — typically
WAV or MP3).

Optional:

- `--n-speakers N` — total clusters to fit. Default 3 (interviewer,
  participant, plus one cluster that absorbs noise / overlaps / a third
  speaker).
- `--model SIZE` — `tiny`, `base`, `small`, `medium`, `large-v3`, or
  `large-v3-turbo` (default).
- `--language en` — kept explicit; do not let Whisper auto-detect for
  English interview data (it occasionally misfires on the first few
  seconds).

## Stage 1 — `transcribe_diarize.py`

Run `scripts/transcribe_diarize.py`:

```bash
python3 scripts/transcribe_diarize.py \
    --audio interview.wav \
    --out   interview_full.JSON \
    --n-speakers 3
```

What happens internally:

1. **Long-recording split.** ffprobe checks the audio duration. If it
   exceeds 20 min (1200 s), the file is split into N equal-length
   chunks where N is the smallest integer that keeps every chunk under
   20 min (`N = ceil(duration / 1200)`). Splits happen via
   `ffmpeg -c copy` (no re-encode) into a temp directory. Files at or
   under 20 min are not split.
2. **Whisper per chunk.** faster-whisper transcribes each chunk with
   word-level timestamps. Per-chunk segment timestamps are shifted by
   the chunk's start offset so the merged segment list lives on the
   original-recording timeline. The merge happens before any
   diarization runs.
3. **ECAPA embeddings.** The full audio (not the chunks) is loaded as
   a 16 kHz mono tensor (torchaudio); for each merged segment of
   duration ≥ 0.5 s, a SpeechBrain ECAPA-TDNN embedding is computed.
4. **Clustering.** Embeddings are L2-normalized and clustered with
   `AgglomerativeClustering(n_clusters=N, metric="cosine",
   linkage="average")`. Segments shorter than 0.5 s inherit the label
   of the nearest valid segment (preferring the preceding one).
   Diarization runs on the full audio so cluster IDs stay consistent
   across chunk boundaries.
5. **Role heuristic.** The cluster that dominates the first 60 s of
   speech is labeled `interviewer`; among the remaining clusters, the
   one with the most total speech time gets `participant`; the rest
   are `extra speaker`.
6. The Rev-style JSON is written with `speaker_map` populated and
   `selected_speaker = null` (set by stage 3).

## Stage 2 — Speaker selection + voice-type (HITL)

After stage 1 finishes, Claude does **not** silently pick a speaker.
Instead:

1. **Sanity-check the diarization.** Compute each cluster's share of
   total speech time. If any single cluster has ≥ 90 % of speech, that
   is almost certainly diarization failure (one cluster has absorbed
   both real speakers — usually because the two voices are too similar
   for ECAPA-TDNN, or because Whisper segments span speaker
   boundaries). Surface this to the user before asking which speaker
   to analyze, and recommend either re-running with a different
   `--n-speakers`, or skipping this recording.

2. **Inspect each cluster.** Total speech time, first-60-s share, and
   a sample of three short turns per cluster. Look for cues — *who
   asks questions*, *who gives long monologue answers*, *who delivers
   the "today is …, my name is …, we are speaking with …" preamble*.

3. **Present the guess and ask for two confirmations** in a single
   prompt:
   - Which speaker to analyze (the heuristic guess is the cluster
     labeled `participant`).
   - Voice type for that speaker: `low` (typically male / lower-pitched
     → `--sex m`, max formant 5000 Hz) or `high` (typically female /
     higher-pitched → `--sex f`, max formant 5500 Hz). FAVE's
     mahalanobis formant predictor and the Praat extractor both need
     this — a wrong choice silently shifts F1 / F2 by hundreds of Hz.

   Format the prompt with **numbered, button-style options** so the
   user can answer with a click rather than free text. When several
   recordings are queued, group the prompts together and number them
   per recording (e.g. `1. Brownsville_KR`, `2. Corpus_Christi_SH`).

4. Wait for the user's response. Then run stage 3 with the chosen
   speaker ID. Pass the voice type forward so it reaches the FAVE
   speaker file (`--sex`) and the Praat extractor (`--voice`).

**Skipping the prompt.** If the meta-skill is invoked with
`--no-confirm`, stage 2 takes the heuristic guess (the cluster
labeled `participant`) and defaults voice type to `low`. The
`--no-confirm` mode is for batch reruns *after* the user has
validated voice type once on the same recording — surface this clearly
so users don't get a silent wrong default.

## Known limitation — diarization architecture

ECAPA-TDNN embeddings are computed per Whisper segment. Whisper
segments break on sentence / breath boundaries, not speaker
boundaries — so when one segment spans an
interviewer-question→participant-answer transition, ECAPA produces
one mixed-voice embedding for both speakers, and clustering treats
them as one cluster. This shows up as the lopsided-cluster failure
above (one cluster ~99 % of speech, the other a handful of
interjections). Two fixes, both planned for v2:

- Run a VAD pass (e.g. `silero-vad` or pyannote.audio's segmentation)
  before Whisper so speaker boundaries land between Whisper segments,
  not inside them.
- Or replace the ECAPA + agglomerative pipeline with
  pyannote.audio's pretrained `speaker-diarization-3.x` end-to-end.

For v1, document the limitation, surface the lopsided-cluster warning
loudly, and skip recordings that trip it.

## Stage 3 — `filter_speaker.py`

```bash
python3 scripts/filter_speaker.py \
    --in  interview_full.JSON \
    --speaker 2 \
    --out interview.JSON
```

Drops every monologue whose `speaker` ID isn't the selected one,
preserves `speaker_map`, and writes `selected_speaker` to the chosen
ID. The output filename **must** lose the `_full` suffix and become
the canonical `<basename>.JSON` so downstream skills find it without
extra arguments.

## Notes

- **Disfluencies stay in.** Filler words (uh, um, like, y'know),
  false starts, repetitions, self-corrections — these are the data,
  not noise. Do not "clean up" the transcript.
- **Pre-emphasis on first 60 s.** The interviewer-detection heuristic
  assumes the recording starts with the interviewer's preamble. If a
  recording instead opens with the participant talking, the heuristic
  will misfire — that's exactly why stage 2 asks the user to confirm.
- **Word-confidence threshold:** Whisper word probabilities below 0.5
  flag uncertain transcription. Surface aggregate counts in the
  summary so the user knows whether to skim the JSON before alignment.
- **Diarization quality** depends heavily on audio quality. Crosstalk,
  speakers with similar timbre, or one speaker dominating ≥ 95 % of
  speech tend to break clustering. Note any of these in the summary.
- For very long recordings (> 1 h), Whisper may take 10–20 min. The
  diarization step is fast by comparison.

## Citations

- Whisper: Radford A et al. (2023). "Robust Speech Recognition via
  Large-Scale Weak Supervision."
- faster-whisper / CTranslate2: Klein G et al. CTranslate2 inference
  engine.
- SpeechBrain ECAPA-TDNN: Desplanques B, Thienpondt J, Demuynck K
  (2020). "ECAPA-TDNN: Emphasized Channel Attention, Propagation and
  Aggregation in TDNN Based Speaker Verification." *Interspeech 2020*.
