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

## Quick start (lightweight path)

```bash
# 1. install (one-time)
pip3 install requests soundfile pyyaml \
    faster-whisper speechbrain scikit-learn torchaudio
brew install ffmpeg praat                 # or apt-get install ffmpeg + build praat

# 2. install the four skills
ln -s "$(pwd)/transcribe-en"      ~/.claude/skills/transcribe-en
ln -s "$(pwd)/align-en"           ~/.claude/skills/align-en
ln -s "$(pwd)/vowel-extract-en"   ~/.claude/skills/vowel-extract-en
ln -s "$(pwd)/formant-extraction" ~/.claude/skills/formant-extraction

# 3. run the meta-skill on an interview
#    (in Claude Code)
/formant-extraction interview.wav --backend webmaus --extractor praat
```

The meta-skill walks you through transcription → speaker selection →
alignment → vowel extraction, pausing at each stage so you can review the
output before continuing. Use `--no-confirm` to run without pauses.

For the FAVE/MFA path (heavier install, FAVE-style 39-column CSV
output), see [INSTALL.md](INSTALL.md).

## Third-party tools and licenses

This toolkit invokes several external tools. None ship with the repo;
install them separately.

- **BAS WebMAUS API** — free for academic / non-commercial use; data
  deleted from BAS servers within 24 h; sleep ≥ 0.5 s between calls
  (rate-limit etiquette). Cite: Kisler T, Reichel U, Schiel F (2017).
  *Computer Speech and Language* 45, 326–347.
- **Montreal Forced Aligner (MFA)** — MIT. Cite: McAuliffe M, Socolof M,
  Mihuc S, Wagner M, Sonderegger M (2017). MFA toolkit. *Interspeech 2017*.
- **FAVE-extract / FAVE-align** — MIT. Cite: Rosenfelder I, Fruehwald J,
  Evanini K, Yuan J. FAVE (Forced Alignment & Vowel Extraction).
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

## What v1 supports

Monolingual American English interview audio. The user picks two
options at invocation:

- **Alignment backend:** `fave` (Montreal Forced Aligner with the
  `english_us_arpa` model — ARPA labels, heavier install) or `webmaus`
  (BAS WebMAUS API — X-SAMPA labels, lightweight install).
- **Vowel extractor:** `fave` (FAVE-extract, paired with MFA output,
  classic FAVE 39-column CSV plus Lobanov-normalized formants) or
  `praat` (headless Praat script, reads either ARPA or X-SAMPA via
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
