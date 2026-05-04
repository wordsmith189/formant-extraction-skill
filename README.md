# formant-extraction-skill

Four Claude Code skills for taking a monolingual English interview recording
from raw audio to a vowel-formant CSV.

- `transcribe-en/` — transcribe and diarize the recording.
- `align-en/` — force-align audio and transcript to word + phone level.
  Backend: FAVE/MFA or BAS WebMAUS.
- `vowel-extract-en/` — extract vowel formants from an aligned TextGrid.
  Extractor: FAVE-extract or a headless Praat script.
- `formant-extraction/` — meta-skill that runs the three above and asks the
  user to pick the start point, alignment backend, and extractor.

v1 covers English only. Bilingual support is planned and will reuse
`align-en`'s WebMAUS branch.

The v1 suite runs in either **Claude Cowork** (the Claude desktop
app) or **Claude Code** (the CLI / IDE extension). The prompts below
work in both; the only difference is where the skills directory
lives. The skills shell out to local binaries (ffmpeg, sox, Praat,
MFA, FAVE-extract) and read/write files on disk, so they don't run
in claude.ai chat — its skill sandbox has no access to your audio
files or those CLIs.

## Quick start

You drive this toolkit by prompting Claude. The five skills
(`formant-extraction-setup`, `transcribe-en`, `align-en`,
`vowel-extract-en`, and the `formant-extraction` meta-skill) do the
work; you tell Claude which one to invoke and on what file.

### 1. Set up the installables (one-time)

After cloning the repo, symlink the setup skill into Claude's skills
directory:

```bash
ln -s "$(pwd)/formant-extraction-setup" ~/.claude/skills/formant-extraction-setup
```

Then in Claude Code, prompt:

> **Run `/formant-extraction-setup` for the FAVE/MFA path.**

The setup skill detects your OS and architecture, asks which pipeline
path you want (lightweight WebMAUS+Praat or heavyweight FAVE/MFA),
installs missing dependencies (Python packages, ffmpeg, sox, Praat,
MFA via micromamba, the Praat wrapper for headless FAVE-extract),
symlinks the remaining three skills into `~/.claude/skills/`, and
verifies the install. Swap `FAVE/MFA` for `WebMAUS` in the prompt for
the lightweight path.

For a manual install, see [INSTALL.md](INSTALL.md).

### 2. Run the whole pipeline on one audio file

Put a recording in your project directory and prompt:

> **Run `/formant-extraction` on `interview.wav` end-to-end.**

The meta-skill walks the file through transcription → speaker
selection → forced alignment → vowel extraction, pausing at two
human-in-the-loop gates so you can correct the transcript and verify
alignment boundaries in Praat before continuing. The defaults are
FAVE/MFA alignment plus FAVE-extract — switch to the lightweight path
by adding "use the WebMAUS backend and the Praat extractor" to the
prompt. Add "skip the confirmation gates" once you've validated the
recording end-to-end and want to re-run unattended.

### 3. Run only part of the pipeline

The three sub-skills can be invoked on their own. If you already have
a transcript and just want alignment + vowel extraction, prompt:

> **I have `interview.wav` and `interview.json` (a Rev-style
> transcript — JSON output from [Rev.ai](https://www.rev.ai/)'s
> speech-to-text service).
> Run `/align-en` on them, then run `/vowel-extract-en` on the resulting
> TextGrid. Skip transcription.**

The transcript does not have to be Rev-style JSON. `align-en` also
accepts a **Praat `.TextGrid`** with an utterance-level interval tier
(empty intervals are treated as silence) and a **plain `.txt`** file
of running prose (WebMAUS backend only — FAVE/MFA needs the
utterance-level TextGrid). For a TextGrid transcript:

> **I have `interview.wav` and `interview.TextGrid` (utterance-level
> intervals on a single tier). Run `/align-en` on them with the
> WebMAUS backend, then `/vowel-extract-en` on the aligned TextGrid.**

Equivalent meta-skill form:

> **Run `/formant-extraction` on `interview.wav` starting from the
> transcript at `interview.TextGrid` (use `--from transcript`).**

Other entry points:

- Transcribe only: *"Run `/transcribe-en` on `interview.wav`."*
- Align only (already have transcript): *"Run `/align-en` on
  `interview.wav` with `interview.json`."* (or `.TextGrid` / `.txt`)
- Extract only (already have an aligned TextGrid): *"Run
  `/vowel-extract-en` on `interview.TextGrid` with `interview.wav`."*

Each sub-skill writes its outputs next to its inputs, so chaining
them by hand gives you the same artifacts as the meta-skill, minus
the review gates.

### 4. Batch processing

For a set of recordings, run the full pipeline on one file before
starting the next — laterally through the pipeline, not vertically
through the stack. Sample prompt:

> **I have `interview1.wav`, `interview2.wav`, and `interview3.wav`
> in the current directory. For each one in turn, run
> `/formant-extraction` end-to-end before moving to the next file.**

Going one file at a time means you catch transcription or
diarization problems on file 1 before they propagate through three
stages on every other file in the batch. The gates at transcription
and alignment exist for that reason; processing the whole batch
through `/transcribe-en` first would either bypass the gates or stall
the whole batch on the first review pause.

## Third-party tools and licenses

This toolkit invokes several external tools. None ship with the repo;
this skill installs them separately as needed.

- **BAS WebMAUS API** — free for academic / non-commercial use; data
  deleted from BAS servers within 24 h; sleep ≥ 0.5 s between calls
  (rate-limit etiquette). See the "Citing FAVE and WebMAUS" section
  below for the full citation.
- **Montreal Forced Aligner (MFA)** — MIT. Cite: McAuliffe M, Socolof M,
  Mihuc S, Wagner M, Sonderegger M (2017). MFA toolkit. *Interspeech 2017*.
- **FAVE-extract / FAVE-align** — GPL-3.0. See the "Citing FAVE and
  WebMAUS" section below for the full citation.
- **Whisper / faster-whisper** — MIT. Cite: Radford A et al. (2023).
  "Robust Speech Recognition via Large-Scale Weak Supervision."
- **SpeechBrain** (ECAPA-TDNN speaker embeddings used for diarization)
  — Apache 2.0. Cite: Desplanques B, Thienpondt J, Demuynck K (2020).
  "ECAPA-TDNN: Emphasized Channel Attention, Propagation and Aggregation
  in TDNN Based Speaker Verification." *Interspeech 2020*. Toolkit:
  Ravanelli M et al. (2021). *SpeechBrain*.
- **Praat** — GPL. Cite: Boersma P, Weenink D. *Praat: doing phonetics
  by computer* (any version).

This repo's own code is licensed under [MIT](LICENSE).

## Citing FAVE and WebMAUS

If you publish work using the **FAVE/MFA path**, cite the FAVE program
suite. The repository ships a `CITATION.cff`; the canonical software
citation is:

- Rosenfelder, I., Fruehwald, J., Brickhouse, C., Evanini, K.,
  Seyfarth, S., Gorman, K., Prichard, H., & Yuan, J. (2022). *FAVE:
  Forced alignment and vowel extraction* (v2.0.1) [Computer software].
  GitHub. <https://github.com/JoFrhwld/FAVE>

The original 2011 release is still cited for comparability with
older studies:

- Rosenfelder, I., Fruehwald, J., Evanini, K., & Yuan, J. (2011).
  *FAVE (Forced Alignment and Vowel Extraction) Program Suite.*
  <http://fave.ling.upenn.edu>

If you publish work using the **WebMAUS path**, the BAS terms of use
ask for two references — the MAUS algorithm and the web-services
wrapper — plus an institutional acknowledgment:

- Schiel, F. (1999). Automatic phonetic transcription of non-prompted
  speech. In *Proceedings of the 14th International Congress of
  Phonetic Sciences (ICPhS)* (pp. 607–610). San Francisco.
- Kisler, T., Reichel, U. D., & Schiel, F. (2017). Multilingual
  processing of speech via web services. *Computer Speech & Language*,
  *45*, 326–347. <https://doi.org/10.1016/j.csl.2017.01.005>

Acknowledge the **Bavarian Archive for Speech Signals (BAS),
Institute of Phonetics and Speech Processing, Ludwig-Maximilians-
Universität München** in publications that use any BAS web service.

For the remaining tools (MFA, Whisper / faster-whisper, SpeechBrain,
Praat), see the short citations under "Third-party tools and
licenses" above.

## Citing this toolkit

Until a Zenodo DOI is registered (see below), cite the GitHub
repository directly:

- Hinrichs, L. (2026). *formant-extraction-skill: Claude-driven
  forced alignment and vowel-formant extraction for monolingual
  English interviews* (v1) [Computer software]. GitHub.
  <https://github.com/wordsmith189/formant-extraction-skill>

A `CITATION.cff` is included so GitHub shows a "Cite this
repository" button on the repo page.

### Getting a DOI via Zenodo

[Zenodo](https://zenodo.org) mints free DOIs for archived GitHub
releases. To register one for this repo:

1. Sign in to Zenodo with your GitHub account.
2. Go to *GitHub* in your Zenodo account settings and toggle archiving
   on for `wordsmith189/formant-extraction-skill`.
3. Cut a GitHub release (e.g. `v1.0.0`) — Zenodo archives the tagged
   snapshot and assigns a per-release DOI plus a *concept DOI* that
   always resolves to the latest version.
4. Add both DOIs to `CITATION.cff` and update this section's citation
   to use the concept DOI.

## What v1 supports

Monolingual American English interview audio. The user picks two
options at invocation:

- **Alignment backend:** `fave` (Montreal Forced Aligner with the
  `english_us_arpa` model — ARPA labels, heavier install) or `webmaus`
  (BAS WebMAUS API — X-SAMPA labels, lightweight install).
- **Vowel extractor:** `fave` (FAVE-extract, paired with MFA output —
  canonical 16 columns plus FAVE extras such as Lobanov-normalized
  formants and Plotnik vowel-class labels appended after column 16)
  or `praat` (headless Praat script, reads either ARPA or X-SAMPA via
  `references/vowel-sets.yaml`).

Both extractors emit the canonical 16-column CSV defined in
[references/csv-schema.md](references/csv-schema.md).

## Verified in v1

End-to-end FAVE/MFA path on two real Texas English interview recordings
(May 2026):

- **Language_Del_Rio_AS** — 12 min, 1 chunk, 791 vowels × 5 timepoints,
  24 outliers (3.0 %).
- **Language_Brownsville_KR** — 37 min, 2 chunks (exercised the
  20-minute split rule), 3 442 vowels × 5 timepoints, 116 outliers
  (3.4 %).

Both CSVs conform to the canonical schema. The 20-minute split rule
(transcribe-en automatically splits long files into ≤ 20-min chunks
and merges segments onto the original timeline) was exercised on the
Brownsville recording and produced a clean unified transcript.

## Known limitations

- **Diarization fails on similar-timbre speakers.** ECAPA-TDNN is run
  per Whisper segment; when a single Whisper segment spans an
  interviewer-question → participant-answer transition, ECAPA produces
  a mixed-voice embedding and clustering treats both speakers as one
  cluster. A third Texas English recording in the verification batch
  hit this failure mode. The skill detects it (cluster ≥ 90 % of
  speech triggers a warning) but doesn't fix it; the v2 plan is
  VAD-based segmentation before Whisper, or pyannote.audio's
  pretrained pipeline. See `transcribe-en/SKILL.md` →
  *Known limitation — diarization architecture*.
- **No bilingual support yet.** `--mode en` is the only legal value
  for v1. Bilingual TxE/TxG support is planned and will reuse
  `align-en --backend webmaus` (which already supports any WebMAUS
  language code) plus per-language splitting.
- **WebMAUS branch and Praat extractor branch are coded but not yet
  end-to-end tested** in this verification round. The FAVE/MFA path is
  the only fully validated configuration.
- **FAVE 2.0.2 has a `writeLog` `UnboundLocalError`** when run outside
  a git repo. The skill wraps the call so this non-fatal exit doesn't
  abort the pipeline (see `vowel-extract-en/SKILL.md`).

## Status

v1, English only. The `align-en` WebMAUS backend is the intended
foundation for v2 bilingual support since WebMAUS already supports
many languages.
