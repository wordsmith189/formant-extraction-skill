---
name: vowel-extract-en
description: >
  Extract vowel formant measurements (F1, F2, F3 plus bandwidths) from a
  word + phone aligned TextGrid for monolingual American English audio.
  Two extractor backends, picked by the user at invocation: `fave` runs
  FAVE-extract on MFA-aligned TextGrids (ARPA phone set, Mahalanobis
  formant prediction, FAAV measurement point, Lobanov normalization);
  `praat` runs a headless Praat script that walks the phone tier and
  measures formants at five timepoints per vowel (works with X-SAMPA
  output from WebMAUS or ARPA output from MFA). Both extractors emit
  the canonical CSV defined in `references/csv-schema.md`. Use whenever
  the user asks to extract vowel formants from an aligned interview, or
  to run FAVE / a Praat formant script on a TextGrid.
---

# vowel-extract-en — vowel formant extraction

Pulls F1/F2/F3 and bandwidths from each vowel interval in an aligned
TextGrid and writes the canonical CSV
(`references/csv-schema.md` at the repo root). Two extractors:

| Extractor | Reads                                | Phone set | Per-vowel rows | Lobanov norms |
|-----------|--------------------------------------|-----------|----------------|---------------|
| `fave`    | MFA-aligned TextGrid (`words`/`phones` tiers, ARPA labels) | ARPA  | 5 (20/35/50/65/80%) | yes |
| `praat`   | any aligned TextGrid (ARPA or X-SAMPA)                     | both  | 5 (20/35/50/65/80%) | no (do post-hoc) |

Both extractors emit the same first 16 columns. The `fave` extractor
appends FAVE-specific extras (Lobanov normalization, Plotnik vowel
class, etc.) after column 16. Code that reads these CSVs should select
columns by name, not by position past 16.

## Inputs

1. **Audio** — the recording the TextGrid was aligned to.
2. **Aligned TextGrid** — output of `align-en`. Both backends produce
   tiers named `words` and `phones`; they differ in the phone label
   set, not in tier names. The valid extractor is determined by the
   phone label set, not by the tier name:

   | Phone label set                        | Came from                | Valid extractors      |
   |----------------------------------------|--------------------------|-----------------------|
   | ARPA — `AA1`, `IH0`, `B`, …            | `align-en --backend fave` (MFA) | `fave` or `praat` |
   | X-SAMPA — `i:`, `{`, `@`, `dZ`, …      | `align-en --backend webmaus`     | `praat` only      |

## Extractor selection rule

`--extractor fave` is only valid when the phone tier contains ARPA
labels (uppercase letters with optional stress digit). FAVE-extract
expects ARPA + the FAVE/MFA TextGrid format and would either crash or
produce nonsense on X-SAMPA input. Reject the combination *before*
invoking FAVE-extract.

Tier names alone are no longer a reliable signal — MFA's
`--single_speaker` mode also emits bare `words` / `phones` tier names
(the same names the WebMAUS branch uses after rename). Detection must
peek at phone labels:

```python
import re

content = open(textgrid).read()
# pull phone labels from the second `IntervalTier` block (… very
# loosely; see scripts/run_praat_extractor.py:_phones_block_labels for
# the production version)
labels = re.findall(r'text = "([^"]+)"', content.split("phones")[-1])
arpa_share = sum(1 for lab in labels if re.match(r"^[A-Z]+\d?$", lab)) / max(len(labels), 1)
phoneset = "arpa" if arpa_share >= 0.8 else "xsampa"

if extractor == "fave" and phoneset != "arpa":
    sys.exit(
        "ERROR: --extractor fave needs ARPA labels (e.g. AA1, IH0). "
        f"Detected phoneset={phoneset}. Use --extractor praat with "
        "WebMAUS-aligned TextGrids, or re-run align-en with --backend fave."
    )
```

`run_praat_extractor.py` does this detection in `detect_backend()`
(see `_phones_block_labels` and `ARPA_LABEL_RE`). When the phones
tier is empty or the tier names match neither pattern, it aborts;
otherwise it picks ARPA when ≥ 80 % of phone labels match the ARPA
regex and falls back to X-SAMPA otherwise. The meta-skill must run
the extractor-vs-phoneset check **before** invoking either extractor
so the error message is clean.

## Prerequisites

| Tool       | Check                              | Used by      |
|------------|------------------------------------|--------------|
| Praat      | `which praat`                      | both extractors |
| Python 3 + pyyaml | `python3 -c "import yaml"`  | praat extractor |
| FAVE 2.x   | `python3 -c "import fave"`         | fave extractor |
| fave-extract on PATH | `which fave-extract`     | fave extractor |
| sox        | `which sox`                        | fave extractor |
| Praat wrapper at `/tmp/bin/praat` | `test -x /tmp/bin/praat` | fave extractor (headless wrapper) |

## Pipeline — `praat` extractor

Calls `scripts/run_praat_extractor.py`, which:

1. Reads the TextGrid header to confirm tier names — aborts if neither
   pair (`<spk> - words/phones` or bare `words/phones`) is present.
2. Picks the phone-set inventory (ARPA vs X-SAMPA) from
   `references/vowel-sets.yaml` based on **phone label content**: ARPA
   if ≥ 80 % of non-empty phone labels match `^[A-Z]+\d?$`, X-SAMPA
   otherwise. (Tier names alone are no longer enough — MFA's
   `--single_speaker` mode strips the speaker prefix, so MFA and
   WebMAUS both emit bare `words`/`phones` tiers.)
3. Writes the vowel list to a temp file and invokes Praat `--run` on
   `scripts/extract_formants.praat` with these arguments:
   ```
   praat --run extract_formants.praat \
       <audio> <textgrid> <words tier> <phones tier> \
       <vowels.txt> <max formant Hz> <out.tsv>
   ```
   Praat builds one `Formant` object over the whole sound (`To Formant
   (burg)`, 5 formants, 25 ms window, 50 Hz preemphasis), then for each
   phone interval whose label (stress digits stripped) is in the vowel
   list it computes F1/F2/F3 and B1/B2/B3 at five frame-center-bounded
   timepoints (20/35/50/65/80% of the inner duration).
4. Reads the per-(vowel, timepoint) TSV from Praat, applies the
   outlier flag (F1 < 200 or > 1200, F2 < 500 or > 3500, duration <
   30 ms), fills `speaker` from `--speaker` (or audio basename), and
   writes the canonical 16-column CSV.

### Voice / max formant

`--voice low` (default) → `max formant = 5000 Hz`.
`--voice high`          → `max formant = 5500 Hz`.

These match the joren `extract_vowel_formants.praat` defaults and are
the standard low-formant / high-formant settings for adult voices in
the FAVE/MFA tradition.

### Invocation

```bash
python3 scripts/run_praat_extractor.py \
    --audio    interview.wav \
    --textgrid interview_aligned.TextGrid \
    --speaker  interview \
    --voice    low \
    --out      interview_vowels.csv
```

## Pipeline — `fave` extractor

This wraps Steps 5–6 of the legacy `tell-align-extract` flow: run
FAVE-extract on the MFA-aligned corpus, then post-process its
tab-delimited `.txt` plus `_norm.txt` into the canonical CSV via
`scripts/fave_to_csv.py`.

### Step 1 — Praat wrapper for headless FAVE

FAVE calls the bare `praat` binary without `--run`, which on macOS
crashes when there's no GUI. Install a wrapper once per machine:

```bash
mkdir -p /tmp/bin
cat > /tmp/praat-wrapper << 'EOF'
#!/bin/bash
exec /opt/homebrew/bin/praat --run "$@"
EOF
chmod +x /tmp/praat-wrapper
ln -sf /tmp/praat-wrapper /tmp/bin/praat
```

Then prepend `/tmp/bin` to `PATH` when invoking `fave-extract`.

### Step 2 — Speaker file

FAVE wants speaker metadata. Avoid the interactive prompt by writing a
`.speaker` file to the working directory:

```text
--name
<speaker>
--sex
m            # 'm' or 'f'; only affects voice typing in FAVE summaries
--location
<location or "unknown">
--speakernum
1
```

**Use `--speakernum 1`, not `--tiernum 0`** — FAVE 2.0.2 has a known
bug where `--tiernum` is read as a string and trips a `TypeError`.

### Step 3 — Run FAVE-extract

```bash
PATH="/tmp/bin:$PATH" fave-extract \
    "<audio_16k.wav>" \
    "<interview_aligned.TextGrid>" \
    "<workdir>/<basename>_output" \
    --mfa \
    --speechSoftware Praat \
    --formantPredictionMethod mahalanobis \
    --measurementPointMethod faav \
    --outputFormat txt \
    --speaker "<workdir>/<basename>.speaker"
```

**Known non-fatal bug.** FAVE 2.0.2 hits an `UnboundLocalError` for
`changes` in `writeLog()` when the cwd isn't a git repo. The `.txt`
and `_norm.txt` outputs are fully written before the crash; only the
post-write log step fails. Two ways to handle it in practice:

1. Wrap the call so a non-zero exit doesn't bubble up:
   ```bash
   PATH="/tmp/bin:$PATH" fave-extract … || true
   ```
   Then check that both output files exist and have the expected row
   count.
2. Or run inside a git repo (initialize an empty one in the work dir
   if needed) — `writeLog()` reads from `git status` to populate
   `changes`, so the bug doesn't fire.

The meta-skill in `formant-extraction/SKILL.md` uses the `|| true`
form so a single crash doesn't abort the whole pipeline.

### Step 4 — Convert to canonical CSV

```bash
python3 scripts/fave_to_csv.py \
    --fave-txt   "<workdir>/<basename>_output.txt" \
    --fave-norm  "<workdir>/<basename>_output_norm.txt" \
    --speaker    "<basename>" \
    --out        "<basename>_vowels.csv"
```

Each FAVE row (one per vowel) becomes five canonical rows (one per
20/35/50/65/80% timepoint), drawing F1/F2 from FAVE's `F1@N%`/`F2@N%`
columns. F3, B1/B2/B3 are reported once per vowel by FAVE and are
copied across all five rows. FAVE extras (Lobanov norms, Plotnik
labels, etc.) are appended after the canonical 16 columns.

The outlier flag is applied during conversion.

## Verification

Both extractors must produce a CSV that:

1. Has the canonical 16 columns in the order defined by
   `references/csv-schema.md`.
2. Has exactly five rows per vowel (one per timepoint), in
   measurement-point order.
3. Has `flag = "outlier"` on rows that meet the F1/F2/duration
   thresholds and `flag = ""` on the rest.

Spot-check the praat extractor by opening one of its vowel intervals
in Praat's GUI and confirming F1/F2 at 50% match within ±20 Hz. If
they don't, check `--voice` (low vs high max formant) and confirm
the audio is at least 16 kHz mono.

Compare the fave extractor against the legacy `tell-align-extract`
output on the same audio + TextGrid: ignoring the canonical-row
expansion (5x), F1/F2/F3 values should match exactly.

## Use with the bilingual pipeline

`vowel-extract-en` is the only valid extractor when the meta-skill
runs in `--mode bilingual`. Two practical implications:

- **`--extractor fave` is rejected.** FAVE-extract requires ARPA
  labels and is English-only. The meta-skill blocks the combination
  before reaching this skill.
- **Phone label set comes from `align-bi`.** Default is X-SAMPA
  (already covered by the `xsampa` block in
  `references/vowel-sets.yaml`); the user can opt into IPA via
  `--phone-symbols ipa` on `align-bi`. See "IPA labels" below for
  the extra step IPA requires.

The `--voice low` / `--voice high` flag is **identical** in
monolingual and bilingual modes — it controls the Praat max-formant
ceiling (5000 Hz vs 5500 Hz) and the same gate-1 prompt that asked
for it in the English path runs verbatim in the bilingual path.

### IPA labels

If `align-bi` was run with `--phone-symbols ipa`, the phone tier
contains IPA characters (`iː`, `æ`, `ɑ`, `ə`, `tʃ`, `β`, …). The
shipped `references/vowel-sets.yaml` only has `arpa` and `xsampa`
inventories — IPA labels won't match any of those. Two options:

1. **Add an `ipa` block to `vowel-sets.yaml`** listing the IPA vowel
   symbols for the languages in the recording, then call the Praat
   extractor with `--phoneset ipa` (the script's phoneset detector
   falls through to whichever block matches the dominant label
   pattern).
2. **Stay in X-SAMPA.** Re-run `align-bi` with `--phone-symbols
   xsampa` (the default). For most projects this is the path of
   least resistance — X-SAMPA is ASCII, the inventory is already in
   `vowel-sets.yaml`, and the Praat extractor handles it without
   any setup.

The meta-skill surfaces this trade-off at gate 2 so the user can
decide before vowel extraction begins.

## Notes

- The Praat extractor takes ~1–2 minutes for a 30-min interview on
  Apple Silicon. The Formant object is computed once over the whole
  sound, so per-vowel cost is just `Get value at time` lookups.
- For very high-pitched speakers or children, override `--voice high`.
  The default is conservative for adult interview data.
- `references/vowel-sets.yaml` defines which symbols count as vowels.
  Edit it (or pass `--vowel-sets <path>`) to extend the inventory
  without touching the Praat script.
