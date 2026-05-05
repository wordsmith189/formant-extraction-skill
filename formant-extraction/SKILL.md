---
name: formant-extraction
description: >
  End-to-end vowel-formant extraction for interview audio in two
  modes: monolingual American English (transcribe-en → align-en →
  vowel-extract-en) or bilingual two-language data (transcribe-bi →
  align-bi → vowel-extract-en). The first thing the meta-skill does
  is ask whether the recording is monolingual English or bilingual;
  in the bilingual case it asks two follow-up questions to identify
  L1 and L2, with four pre-set options ((fairly standard) English,
  Mandarin, Spanish, Russian) plus an "Other" free-text field for
  regiolects, sociolects, or any other supported language. Pauses
  at two human-in-the-loop gates by default — once after
  transcription so the user can correct the text, once after
  alignment so the user can verify boundaries in Praat — both
  skippable with `--no-confirm`. Use whenever the user asks for a
  full audio-to-CSV pipeline on an interview (monolingual or
  bilingual), or wants Claude to handle the whole transcription /
  alignment / vowel extraction sequence in one shot.
---

# formant-extraction — meta-skill

> **First time?** Run `/formant-extraction-setup` before this skill.
> It installs all dependencies and creates the skill symlinks automatically.

Runs three sub-skills in order. Which three depends on `--mode`:

```text
audio
  │
  ├─ MONOLINGUAL ENGLISH  (--mode en, default)
  │   └─ transcribe-en             (Whisper EN + diarization + speaker selection)
  │        │     ↓ Rev-style JSON for one speaker
  │        │   ── HITL gate 1 ──
  │        │
  │        └─ align-en             (FAVE/MFA  or  WebMAUS API)
  │             │     ↓ aligned TextGrid (words + phones)
  │             │   ── HITL gate 2 ──
  │             │
  │             └─ vowel-extract-en (FAVE-extract  or  headless Praat)
  │                  ↓
  │                  vowels CSV (canonical schema; see references/csv-schema.md)
  │
  └─ BILINGUAL  (--mode bilingual)
      └─ transcribe-bi             (diarization → language ID → conditioned ASR)
           │     ↓ Rev-style JSON with `language` per monologue
           │   ── HITL gate 1 ──
           │
           └─ align-bi              (WebMAUS API only; per-language chunks;
                │                     X-SAMPA default, IPA optional)
                │     ↓ aligned TextGrid (transcription + words + phones)
                │   ── HITL gate 2 ──
                │
                └─ vowel-extract-en (headless Praat only; FAVE-extract not valid)
                     ↓
                     vowels CSV (canonical schema)
```

This skill writes no code of its own. It asks the user the
monolingual / bilingual question at the top, asks two follow-up
language questions if bilingual, checks flags, fills in defaults,
invokes each sub-skill, and stops at the two gates so the user can
review intermediate output.

## Up-front questions

Before any flag handling, the meta-skill asks the user one or three
questions via `AskUserQuestion`. The flags below let a power user
skip the questions by passing `--mode bilingual --l1 ... --l2 ...`
directly; if any of those is omitted, the corresponding question
fires.

### Question 1 (always) — monolingual or bilingual?

> **Is the data in this recording monolingual (English) or
> bilingual?**
>
> - **Monolingual (English)** — one speaker variety, English only.
>   Routes through `transcribe-en` → `align-en` → `vowel-extract-en`.
>   FAVE/MFA and FAVE-extract are available.
> - **Bilingual** — two languages in the same recording (the same
>   speaker switching, or two speakers using two languages). Routes
>   through `transcribe-bi` → `align-bi` → `vowel-extract-en`.
>   FAVE/MFA is not available; alignment goes through WebMAUS.

If the user picks **Monolingual**, jump to "Invocation" below and
proceed with `--mode en`.

If the user picks **Bilingual**, ask Q2 and Q3.

### Question 2 (bilingual only) — what is the first language used in the data?

> **What is the first language used in the data?**
>
> - **(fairly standard) English**
> - **(fairly standard) Mandarin**
> - **(fairly standard) Spanish**
> - **(fairly standard) Russian**
> - (Other) — free-text field. Use this for a regiolect or sociolect
>   of any of the above (e.g. *Texas English*, *Caribbean Spanish*),
>   or for any other language that WebMAUS supports.

For each pre-set option the meta-skill fills in the Whisper code and
the WebMAUS code from this lookup table:

| Button label                | Whisper code | WebMAUS code |
|-----------------------------|--------------|--------------|
| (fairly standard) English   | `en`         | `eng-US`     |
| (fairly standard) Mandarin  | `zh`         | `cmn-CN`     |
| (fairly standard) Spanish   | `es`         | `spa-MX`     |
| (fairly standard) Russian   | `ru`         | `rus-RU`     |

For "Other," ask the user follow-up: an ISO 639-1 (or 639-3) code if
they know it, otherwise the language name and a note about which
country/region — the meta-skill then looks up the WebMAUS code
against the BAS supported-language list and picks the closest match.
If WebMAUS does not support the language, abort here with a clear
error before transcription starts.

### Question 3 (bilingual only) — what is the second language used in the data?

> **What is the second language used in the data?**
>
> Same four buttons + "Other" as Q2.

The meta-skill stores both answers under `languages.L1` and
`languages.L2` and forwards them to `transcribe-bi` and `align-bi`.

### Bilingual → forced defaults

Once `--mode bilingual` is set, several flags are forced and the
user is told why:

- `--backend` is forced to `webmaus`. There is no MFA acoustic model
  spanning two languages; FAVE/MFA is only available in monolingual
  mode.
- `--extractor` is forced to `praat`. FAVE-extract requires ARPA
  labels and is English-only. The headless Praat extractor handles
  X-SAMPA (and IPA, with an extended `vowel-sets.yaml`) and is the
  bilingual default.
- The meta-skill prints a one-line notice before alignment runs:

  > Forced alignment for bilingual data uses the BAS WebMAUS API.
  > Phone labels will be in **X-SAMPA** by default — that's the
  > WebMAUS default, and what the Praat vowel extractor's symbol
  > inventory expects out of the box. If you'd rather have **IPA**
  > labels, say so and I'll re-run alignment with
  > `--phone-symbols ipa`. WebMAUS supports both for every language
  > it covers.

  If the user replies asking for IPA, set
  `--phone-symbols ipa` on the `align-bi` call and remind them at
  gate 2 that the Praat extractor's `vowel-sets.yaml` will need an
  IPA inventory (see `vowel-extract-en/SKILL.md` → "IPA labels").

## Invocation

```text
/formant-extraction <audio> [flags]
```

| Flag             | Values                          | Default                                    | What it does |
|------------------|---------------------------------|--------------------------------------------|--------------|
| `--mode`         | `en`, `bilingual`               | (asked at Q1)                              | Pipeline branch. `en` runs the monolingual stack; `bilingual` runs the bi-language stack. |
| `--l1` / `--l2`  | label or ISO code               | (asked at Q2 / Q3 when `--mode bilingual`) | Override Q2 / Q3 from the command line. Accept the four pre-set labels verbatim or any ISO 639-1 / 639-3 code. |
| `--phone-symbols`| `xsampa`, `ipa`                 | `xsampa` (bilingual only)                  | Phone-label system passed to WebMAUS. Ignored in `--mode en`. |
| `--from`         | `audio`, `transcript`, `aligned-textgrid` | `audio`                          | Where to start the pipeline. |
| `--backend`      | `fave`, `webmaus`               | `fave` in `--mode en`; **forced** to `webmaus` in `--mode bilingual` | Forced-alignment backend. |
| `--extractor`    | `fave`, `praat`                 | mirrors `--backend` in `--mode en`; **forced** to `praat` in `--mode bilingual` | Vowel-extractor backend. |
| `--no-confirm`   | (flag)                          | off                                        | Skip both HITL gates. Use only after the recording's pipeline has already been validated end-to-end with gates active. |
| `--speaker`      | speaker ID or role              | (heuristic during transcribe-* )           | Override the auto-picked speaker. Captured at gate 1 alongside `--voice`. |
| `--voice`        | `low`, `high`                   | (asked at gate 1; `low` only when `--no-confirm`) | Forwarded to FAVE (`--sex m/f`) and Praat (max formant 5000 vs 5500 Hz). Used identically in monolingual and bilingual modes. A wrong value silently shifts F1/F2 by hundreds of Hz, so the meta-skill **asks the user** at gate 1 rather than relying on a silent default. |
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

1. **`--mode`.** Either `en` or `bilingual`. If absent, run Q1 (see
   "Up-front questions" above). Anything else: abort with
   `"--mode must be 'en' or 'bilingual'."`

2. **Bilingual-mode forcings.** When `--mode bilingual` is active:
   - Force `--backend = webmaus`. If the user passed
     `--backend fave`, abort with:

         ERROR: FAVE/MFA does not support bilingual data — there is
         no MFA acoustic model spanning two languages. Bilingual
         alignment is WebMAUS-only. Drop --backend or pass
         --backend webmaus.

   - Force `--extractor = praat`. If the user passed
     `--extractor fave`, abort with:

         ERROR: FAVE-extract requires ARPA labels and is
         English-only. Use --extractor praat with bilingual data.

   - Resolve `languages.L1` and `languages.L2` from `--l1` / `--l2`,
     or fall through to Q2 / Q3.
   - `--phone-symbols` defaults to `xsampa`. If the user has not
     set it, surface the X-SAMPA-vs-IPA notice (see "Bilingual →
     forced defaults") so they can override before alignment runs.

3. **`--backend` × `--extractor` compatibility (monolingual only).**
   If the user passed `--backend webmaus --extractor fave` with
   `--mode en`, abort before transcription:

       ERROR: --extractor fave requires ARPA labels with stress digits
       (e.g. AA1, IH0). The webmaus backend produces X-SAMPA labels
       (e.g. i:, {, @) that FAVE-extract cannot read. Use --extractor
       praat with --backend webmaus, or switch to --backend fave.

4. **Default `--extractor` (monolingual only)** from `--backend` if
   the user didn't pick one (`fave→fave`, `webmaus→praat`). In
   bilingual mode the default is already forced to `praat` (see
   rule 2).

5. **Resolve start point** from `--from`:
   - `audio`              — run all three sub-skills.
   - `transcript`         — expect `<basename>.JSON` next to audio
     (or a `.TextGrid` of utterance intervals, monolingual mode
     only); skip the transcribe stage. In bilingual mode the JSON
     must contain `languages.L1`, `languages.L2`, and a `language`
     field on every monologue (see `transcribe-bi/SKILL.md` →
     "Output").
   - `aligned-textgrid`   — expect `<basename>_aligned.TextGrid`
     next to audio; skip transcribe and align stages, jump straight
     to vowel-extract-en.

6. **Speaker filter on TextGrid input.** If `--from transcript` and
   the file is a `.TextGrid` rather than a `.JSON`, the TextGrid must
   already contain only the target speaker's utterances. Loudly
   document this in the user-facing summary; abort if a `speaker` /
   `INT` / `interviewer` tier shows mixed turns. (TextGrid-as-
   transcript input is monolingual-mode only — bilingual mode
   requires a JSON with the per-monologue language tag.)

## Pipeline

The script paths below assume the sub-skills are installed at
`~/.claude/skills/` (the standard Claude Code skills location, which
is what the symlink commands in `INSTALL.md` set up). If the user
has the skills somewhere else — symlinked from a different location,
or installed under a custom `CLAUDE_SKILLS_DIR` — substitute that
path in each command. The meta-skill should detect this from the
environment when possible rather than hard-coding `~/.claude/skills/`.

The pipeline has the same three logical stages in both modes
(transcribe → align → extract) but invokes different sub-skills.
Read the matching subsection below; gates 1 and 2 are identical
across modes.

### Stage A — Transcribe (`--from audio` only)

#### `--mode en` — invoke `transcribe-en`

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

#### `--mode bilingual` — invoke `transcribe-bi`

```bash
python3 ~/.claude/skills/transcribe-bi/scripts/transcribe_bilingual.py \
    --audio <audio> --out <basename>_full.JSON --n-speakers 3 \
    --l1-whisper <code> --l1-webmaus <code> --l1-label "<label>" \
    --l2-whisper <code> --l2-webmaus <code> --l2-label "<label>"
```

Pass 1 (diarization) → Pass 2 (per-segment language ID restricted to
{L1, L2}) → Pass 3 (language-conditioned ASR). The output JSON
carries both `speaker` and `language` on every monologue. See
`transcribe-bi/SKILL.md` for the schema and the per-pass details.

The same speaker-selection step runs (now augmented with a per-
language readout per cluster — see `transcribe-bi/SKILL.md` → Stage
4). Filter to one speaker with `transcribe-en/scripts/filter_speaker.py`
(language-agnostic; the `language` field rides through unchanged):

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

#### `--mode en` — invoke `align-en`

Convert the Rev-style JSON to an utterance-level TextGrid via the
`align-en` helper (one interval per monologue, gaps between
monologues become empty intervals):

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

#### `--mode bilingual` — invoke `align-bi`

`align-bi` reads the language-tagged JSON directly (no separate
utterance-TextGrid step), splits the audio per monologue, and sends
one WebMAUS call per monologue with `LANGUAGE = languages[L*].
webmaus_code` set per chunk:

```bash
python3 ~/.claude/skills/align-bi/scripts/align_bilingual.py \
    --audio <audio> \
    --json <basename>.JSON \
    --out-dir <out_dir> \
    --phone-symbols <xsampa|ipa>
```

Output is `<basename>_aligned.TextGrid` with three tiers:
`transcription` (one interval per monologue, language tag prefix in
the label), `words`, and `phones`. The phone label set is X-SAMPA
unless `--phone-symbols ipa` was selected. See `align-bi/SKILL.md`
for the chunk-merge details.

#### Gate 2 (after Stage B, unless `--no-confirm`)

Print to the user:

    Stage 2 complete.
      aligned TextGrid: <out_dir>/<basename>_aligned.TextGrid
      tier names: <list>
      word intervals: <N>; phone intervals: <M>; failed chunks: <K>
      [bilingual only] phone label set: <xsampa|ipa>
      [bilingual only] L1 chunks: <ok>/<total>  L2 chunks: <ok>/<total>

    Open the TextGrid in Praat alongside the audio to verify
    boundaries. Resume with:
      /formant-extraction <audio> --from aligned-textgrid \
        --mode <en|bilingual> [--backend <backend>] [--extractor <extractor>]

In bilingual mode also remind the user that `--extractor` is forced
to `praat`, and that if they switched alignment to IPA they may need
to extend `vowel-sets.yaml` (see `vowel-extract-en/SKILL.md` →
"IPA labels") before vowel extraction can match phones.

Then **stop**.

### Stage C — Extract vowels

Invoke `vowel-extract-en` with the chosen extractor. In bilingual
mode the extractor is forced to `praat` (FAVE-extract is English-
only, ARPA-only).

- **`--extractor praat`** (always used in `--mode bilingual`; default
  paired with `--backend webmaus` in `--mode en`):

```bash
python3 ~/.claude/skills/vowel-extract-en/scripts/run_praat_extractor.py \
    --audio    <audio> \
    --textgrid <basename>_aligned.TextGrid \
    --speaker  <basename> \
    --voice    <low|high> \
    --out      <basename>_vowels.csv
```

The `--voice` flag is identical in both modes: `low` → max formant
5000 Hz, `high` → max formant 5500 Hz. The same gate-1 prompt that
captured `--voice` in `--mode en` runs in `--mode bilingual`.

- **`--extractor fave`** (monolingual English only): follow
  `vowel-extract-en/SKILL.md` Steps 1–4 (Praat wrapper, speaker file,
  `fave-extract` command, then `fave_to_csv.py`).

Both paths emit a CSV conforming to `references/csv-schema.md`.

### Final summary

After Stage C, print one block:

    Pipeline complete.
      mode:       <en | bilingual>
      audio:      <path>
      transcript: <path>
      aligned:    <path>
      vowels CSV: <path>
      rows:       <N>  (vowels × 5 timepoints)
      outliers:   <K>  (flag = "outlier" — F1/F2/duration thresholds)
      backend:    <fave|webmaus>     extractor: <fave|praat>
      [bilingual only] L1: <label> (<webmaus_code>)   L2: <label> (<webmaus_code>)
      [bilingual only] phone label set: <xsampa|ipa>

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

- `--mode` not `en` or `bilingual`: abort.
- `--mode bilingual --backend fave`: abort with the message in
  decision rule 2.
- `--mode bilingual --extractor fave`: abort with the message in
  decision rule 2.
- `--mode en --backend webmaus --extractor fave`: abort with the
  message in decision rule 3.
- Bilingual JSON missing the `language` field on monologues: abort
  with a pointer to `transcribe-bi`.
- L1 or L2 not in the WebMAUS supported-language list: abort at
  language-selection time, before transcription.
- Required input file missing for the chosen `--from`: abort with
  the expected path.
- Sub-skill returns non-zero (other than the known FAVE 2.0.2 exit
  code 1, see `vowel-extract-en/SKILL.md`): abort, print the
  sub-skill's stderr.

## Notes

- The skill assumes `transcribe-en`, `transcribe-bi`, `align-en`,
  `align-bi`, and `vowel-extract-en` are installed at
  `~/.claude/skills/` (or symlinked there from this repo). If a
  sub-skill needed for the chosen mode is missing, abort with a
  pointer to `INSTALL.md`.
- The bilingual stack reuses `transcribe-en/scripts/filter_speaker.py`
  for the speaker-filter step, since the language tag is preserved
  across the filter. No bilingual-specific filter script is
  needed.
- The two HITL gates exist so the user can catch Whisper
  hallucinations and alignment drift before they propagate into the
  CSV. Use `--no-confirm` only for batch runs after the pipeline has
  been validated on a known recording.
