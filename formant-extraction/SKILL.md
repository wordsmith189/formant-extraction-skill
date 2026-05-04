---
name: formant-extraction
description: >
  End-to-end vowel-formant extraction for monolingual American English
  interview audio. Orchestrates `transcribe-en` → `align-en` →
  `vowel-extract-en` with three decision points the user controls at
  invocation: where to start (raw audio, transcript, or aligned
  TextGrid), alignment backend (`fave` or `webmaus`), and formant
  extractor (`fave` or `praat`). Pauses at two human-in-the-loop gates
  by default — once after transcription so the user can correct the
  text, once after alignment so the user can verify boundaries in
  Praat — both skippable with `--no-confirm`. Use whenever the user
  asks for a full audio-to-CSV pipeline on an English interview, or
  wants Claude to handle the whole transcription / alignment / vowel
  extraction sequence in one shot.
---

# formant-extraction — meta-skill

Runs the three sub-skills in order:

```text
audio
  │
  └─ transcribe-en               (Whisper + diarization + speaker selection)
       │     ↓ Rev-style JSON for one speaker
       │   ── HITL gate 1 ──
       │
       └─ align-en               (FAVE/MFA  or  WebMAUS API)
            │     ↓ aligned TextGrid (words + phones)
            │   ── HITL gate 2 ──
            │
            └─ vowel-extract-en  (FAVE-extract  or  headless Praat)
                 ↓
                 vowels CSV (canonical schema; see references/csv-schema.md)
```

This skill writes no code of its own. It checks flags, fills in
defaults, invokes each sub-skill, and stops at the two gates so the
user can review intermediate output.

## Invocation

```text
/formant-extraction <audio> [flags]
```

| Flag             | Values                          | Default                                    | What it does |
|------------------|---------------------------------|--------------------------------------------|--------------|
| `--mode`         | `en`                            | `en`                                       | Reserved for v2 bilingual support. `en` is the only legal value in v1. |
| `--from`         | `audio`, `transcript`, `aligned-textgrid` | `audio`                          | Where to start the pipeline. |
| `--backend`      | `fave`, `webmaus`               | `fave`                                     | Forced-alignment backend. |
| `--extractor`    | `fave`, `praat`                 | mirrors `--backend` (`fave→fave`, `webmaus→praat`) | Vowel-extractor backend. |
| `--no-confirm`   | (flag)                          | off                                        | Skip both HITL gates. Use only after the recording's pipeline has already been validated end-to-end with gates active. |
| `--speaker`      | speaker ID or role              | (heuristic during transcribe-en)           | Override the auto-picked speaker. Captured at gate 1 alongside `--voice`. |
| `--voice`        | `low`, `high`                   | (asked at gate 1; `low` only when `--no-confirm`) | Forwarded to FAVE (`--sex m/f`) and Praat (max formant 5000 vs 5500 Hz). A wrong value silently shifts F1/F2 by hundreds of Hz, so the meta-skill **asks the user** at gate 1 rather than relying on a silent default. |
| `--out-dir`      | path                            | beside the audio                           | Write all artifacts here. |

## Time estimates

Print these to the user **before** starting each stage. Numbers below
are wall-clock on a 2026 Apple Silicon laptop, CPU only (no CUDA), no
parallel jobs competing for CPU.

| Stage                               | Rate                                | Example (12-min audio) | Example (37-min audio) |
|-------------------------------------|-------------------------------------|------------------------|------------------------|
| Whisper transcribe (`large-v3-turbo`) | ~0.4× real-time + ~3 min model load (first run only) | ~5 min                 | ~12 min                |
| ECAPA diarization                   | seconds per minute of audio         | ~30 s                  | ~1 min                 |
| MFA align (`--single_speaker`)      | ~5–10 % of audio duration           | ~1 min                 | ~1 min                 |
| WebMAUS align                       | ~1.5 s per chunk + 0.5 s sleep      | depends on chunking    | depends on chunking    |
| FAVE-extract (per vowel)            | ~1 vowel / s on CPU                 | ~7 min (~800 vowels)   | ~30 min (~3500 vowels) |
| Praat extractor                     | <1 min for typical interview        | <1 min                 | <1 min                 |

The meta-skill must compute and show a total estimate before
beginning. If the total is over 20 min, also state which stage is the
bottleneck so the user can decide whether to start now or queue.

**Recordings over 20 min** are split into chunks ≤ 20 min each before
Whisper runs (handled inside `transcribe-en/scripts/transcribe_diarize.py`).
The split is `ffmpeg -c copy` (no re-encode) and adds < 1 s.

## Decision rules

Apply in this order before invoking any sub-skill:

0. **Sanitize the working basename.** Drop the audio extension and
   replace runs of whitespace with a single underscore (e.g.
   `Language_Del Rio_AS_08012025.mp3` → `Language_Del_Rio_AS_08012025`).
   FAVE-extract crashes on filenames with spaces and MFA's corpus dir
   rejects them. The original audio file stays untouched; the
   sanitized name is used for working copies and final output
   filenames. Print the rename to the user so the path mapping is
   visible in the summary.

1. **`--mode`.** Must be `en`. Anything else: abort with
   `"--mode bilingual is not supported in v1; tracking as future work."`
2. **`--backend` × `--extractor` compatibility.** If the user passed
   `--backend webmaus --extractor fave`, abort before transcription:

       ERROR: --extractor fave requires ARPA labels with stress digits
       (e.g. AA1, IH0). The webmaus backend produces X-SAMPA labels
       (e.g. i:, {, @) that FAVE-extract cannot read. Use --extractor
       praat with --backend webmaus, or switch to --backend fave.

3. **Default `--extractor`** from `--backend` if the user didn't pick
   one (`fave→fave`, `webmaus→praat`).
4. **Resolve start point** from `--from`:
   - `audio`              — run all three sub-skills.
   - `transcript`         — expect `<basename>.JSON` next to audio (or
     a `.TextGrid` of utterance intervals); skip transcribe-en.
   - `aligned-textgrid`   — expect `<basename>_aligned.TextGrid` next
     to audio; skip transcribe-en and align-en, jump straight to
     vowel-extract-en.
5. **Speaker filter on TextGrid input.** If `--from transcript` and
   the file is a `.TextGrid` rather than a `.JSON`, the TextGrid must
   already contain only the target speaker's utterances. Loudly
   document this in the user-facing summary; abort if a `speaker` /
   `INT` / `interviewer` tier shows mixed turns.

## Pipeline

### Stage A — Transcribe (`--from audio` only)

Invoke `transcribe-en`:

```bash
python3 ~/.claude/skills/transcribe-en/scripts/transcribe_diarize.py \
    --audio <audio> --out <basename>_full.JSON --n-speakers 3
```

Then run the speaker-selection step (see `transcribe-en/SKILL.md`
stage 2): inspect the JSON, present the heuristic guess plus sample
turns, and ask the user to confirm / swap. With `--no-confirm`, take
the cluster labeled `participant` without prompting.

Filter the JSON to one speaker:

```bash
python3 ~/.claude/skills/transcribe-en/scripts/filter_speaker.py \
    --in <basename>_full.JSON --speaker <id> --out <basename>.JSON
```

#### Gate 1 (after Stage A, unless `--no-confirm`)

Three things happen at this gate, in this order:

1. **Lopsided-cluster check.** If any cluster has ≥ 90 % of total
   speech time, warn the user that diarization probably failed (see
   `transcribe-en/SKILL.md` → "Known limitation"). Offer:
   re-run with a different `--n-speakers`, accept the result anyway
   (with a clear note that the analysis will mix speakers), or skip
   this recording. Do not proceed silently.

2. **Speaker selection + voice type.** Show each cluster's stats and
   sample turns, then ask the user two questions in a single prompt
   with button-style options (and number them per recording when
   several are queued):
   - which speaker ID to analyze (heuristic guess pre-selected);
   - voice type for that speaker: `low` (≈ male, max formant 5000 Hz,
     `--sex m`) or `high` (≈ female, max formant 5500 Hz, `--sex f`).

   Wrong voice type silently shifts F1/F2 by hundreds of Hz, so the
   prompt is mandatory unless `--no-confirm` is set. With
   `--no-confirm`, the default is `low`; tell the user that up front,
   not buried in a help string.

3. **Transcript review pause.** Print:

       Stage 1 complete.
         transcript:       <out_dir>/<basename>.JSON
         selected_speaker: <id> (<role>)
         voice type:       <low|high>
         <N> monologues, <M> words, <K> low-confidence (<0.5)

       Review and correct the JSON if needed (open it, edit text
       values in `monologues[].elements`). Resume with:
         /formant-extraction <audio> --from transcript \\
           --backend <backend> --voice <low|high> --speaker <id>

   Then **stop**. Do not proceed without a fresh invocation.

### Stage B — Align (`--from audio` or `--from transcript`)

Convert the Rev-style JSON to an utterance-level TextGrid via the
`align-en` helper (one interval per monologue, gaps between monologues
become empty intervals):

```bash
python3 ~/.claude/skills/align-en/scripts/json_to_textgrid.py \
    --in    <basename>.JSON \
    --audio <audio> \
    --out   <basename>.TextGrid
```

Then invoke `align-en` with the chosen backend:

- **`--backend fave`:** see `align-en/SKILL.md` Step 2 (fave). MFA
  needs the corpus directory pattern; output is
  `<basename>_aligned.TextGrid` with `words` / `phones` tiers
  containing ARPA labels (MFA's `--single_speaker` mode strips the
  speaker prefix).
- **`--backend webmaus`:** call the helper directly:

```bash
python3 ~/.claude/skills/align-en/scripts/webmaus_align.py \
    --audio <audio> --textgrid <utterance.TextGrid> \
    --out <out_dir>
```

Output is `<basename>_aligned.TextGrid` with `words` / `phones` tiers
(X-SAMPA labels).

#### Gate 2 (after Stage B, unless `--no-confirm`)

Print to the user:

    Stage 2 complete.
      aligned TextGrid: <out_dir>/<basename>_aligned.TextGrid
      tier names: <list>
      word intervals: <N>; phone intervals: <M>; failed chunks: <K>

    Open the TextGrid in Praat alongside the audio to verify
    boundaries. Resume with:
      /formant-extraction <audio> --from aligned-textgrid \
        --backend <backend> --extractor <extractor>

Then **stop**.

### Stage C — Extract vowels

Invoke `vowel-extract-en` with the chosen extractor:

- **`--extractor praat`:**

```bash
python3 ~/.claude/skills/vowel-extract-en/scripts/run_praat_extractor.py \
    --audio    <audio> \
    --textgrid <basename>_aligned.TextGrid \
    --speaker  <basename> \
    --voice    <low|high> \
    --out      <basename>_vowels.csv
```

- **`--extractor fave`:** follow `vowel-extract-en/SKILL.md` Steps 1–4
  (Praat wrapper, speaker file, `fave-extract` command, then
  `fave_to_csv.py`).

Both paths emit a CSV conforming to `references/csv-schema.md`.

### Final summary

After Stage C, print one block:

    Pipeline complete.
      audio:      <path>
      transcript: <path>
      aligned:    <path>
      vowels CSV: <path>
      rows:       <N>  (vowels × 5 timepoints)
      outliers:   <K>  (flag = "outlier" — F1/F2/duration thresholds)
      backend:    <fave|webmaus>     extractor: <fave|praat>

## Resume semantics

`--from transcript`: skips Stage A. Expects a `.JSON` of one speaker
at `<basename>.JSON` (or a `.TextGrid` — see decision rule 5). Stage B
runs normally. Gate 2 still applies unless `--no-confirm`.

`--from aligned-textgrid`: skips Stages A and B. Expects
`<basename>_aligned.TextGrid`. No gates. Stage C runs.

These flags exist precisely so the user can correct intermediate
outputs (Whisper hallucinations, alignment drift) and resume without
re-running the slow earlier stages.

## Errors and aborts

- `--mode` not `en`: abort.
- `--backend webmaus --extractor fave`: abort with the message in
  decision rule 2.
- Required input file missing for the chosen `--from`: abort with the
  expected path.
- Sub-skill returns non-zero (other than the known FAVE 2.0.2 exit
  code 1, see `vowel-extract-en/SKILL.md`): abort, print the
  sub-skill's stderr.

## Notes

- The skill assumes `transcribe-en`, `align-en`, and `vowel-extract-en`
  are installed at `~/.claude/skills/` (or symlinked there from this
  repo). If any sub-skill is missing, abort with a pointer to
  `INSTALL.md`.
- v1 hard-codes `--mode en`. Future bilingual support will reuse the
  WebMAUS branch of `align-en` and add a language-detection /
  per-language alignment step before vowel extraction.
- The two HITL gates exist so the user can catch Whisper
  hallucinations and alignment drift before they propagate into the
  CSV. Use `--no-confirm` only for batch runs after the pipeline has
  been validated on a known recording.
