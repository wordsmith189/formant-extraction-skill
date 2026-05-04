---
name: align-en
description: >
  Force-align an American English audio recording with its transcript at the
  word and phone level, producing a Praat TextGrid with word and phone tiers.
  The user selects the backend at invocation: `fave` (Montreal Forced Aligner
  with the english_us_arpa model — ARPA phone labels, heavy local install,
  pairs with FAVE-extract for formants) or `webmaus` (BAS WebMAUS API with
  eng-US — X-SAMPA phone labels, lightweight install, free for academic use,
  no API key). Use whenever the user asks to force-align an English recording,
  produce a word+phone TextGrid, or run MFA / WebMAUS on an interview.
---

# align-en — English forced alignment

Force-align American English audio with its transcript at the word and
phone level. The user picks one of two backends at invocation. Both
write a Praat TextGrid next to the input audio.

## Output

Both backends produce a TextGrid with two tiers named `words` and
`phones`. They differ in phone label set:

| Backend  | Phone label set | Sample labels        |
|----------|-----------------|----------------------|
| `fave`   | ARPA            | `AA1`, `IH0`, `B`    |
| `webmaus`| X-SAMPA         | `i:`, `{`, `@`, `dZ` |

MFA's `--single_speaker` mode strips the speaker prefix, so the
FAVE/MFA path emits bare `words` / `phones` tiers (not `<spk> - words`
/ `<spk> - phones`). The WebMAUS path renames `ORT-MAU` → `words` and
`MAU` → `phones` so both backends end up with the same tier names.

`vowel-extract-en` distinguishes the two cases by **inspecting phone
label content** (uppercase + optional stress digit → ARPA; mixed-case
or special chars → X-SAMPA), not by tier name alone. Don't expect the
old `<spk> - phones` pattern in v1 output.

## Inputs

An audio file plus a transcript in one of three forms:

1. A Praat `.TextGrid` with an utterance-level interval tier. Empty
   intervals are silence or other-speaker turns to skip.
2. A plain `.txt` file with the full transcript as running prose.
3. A Rev-style JSON from `transcribe-en` — converted to a TextGrid here.

Backend defaults to `fave`. Pass `--backend webmaus` to use the API
instead.

## Prerequisites

Verify before starting. Abort with a clear message if any are missing.

### Common
| Tool     | Check                          | Install |
|----------|--------------------------------|---------|
| Python 3 | `python3 --version`            | system |
| ffmpeg   | `which ffmpeg`                 | `brew install ffmpeg` |

### Backend `fave`
| Tool       | Check                              | Install |
|------------|------------------------------------|---------|
| micromamba | `/tmp/bin/micromamba --version`    | `curl -Ls https://micro.mamba.pm/api/micromamba/osx-arm64/latest \| tar -xvj -C /tmp bin/micromamba` |
| MFA        | `MAMBA_ROOT_PREFIX=/tmp/micromamba /tmp/bin/micromamba run -n mfa mfa version` | `MAMBA_ROOT_PREFIX=/tmp/micromamba /tmp/bin/micromamba create -n mfa -c conda-forge montreal-forced-aligner -y` |
| MFA acoustic model | (downloaded once) | `mfa model download acoustic english_us_arpa` (in env) |
| MFA dictionary     | (downloaded once) | `mfa model download dictionary english_us_arpa` (in env) |
| sox        | `which sox`                        | `brew install sox` |

### Backend `webmaus`
| Tool       | Check                                  | Install |
|------------|----------------------------------------|---------|
| requests   | `python3 -c "import requests"`         | `pip3 install requests` |
| soundfile  | `python3 -c "import soundfile"`        | `pip3 install soundfile` |
| Internet   | `curl -fsS https://clarin.phonetik.uni-muenchen.de/BASWebServices/services/getLoadIndicator` | — |

## Pipeline

Use `/tmp/align_en_<basename>/` as the working directory. All intermediate
files go there. Final outputs are copied beside the original audio.

### Step 0 — Validate and normalize inputs

1. Confirm the audio file exists.
2. **Sanitize the working basename.** Drop the audio extension, then
   replace every run of whitespace with a single underscore (e.g.
   `Language_Del Rio_AS_08012025.mp3` → `Language_Del_Rio_AS_08012025`).
   FAVE-extract crashes on filenames with spaces, and MFA's corpus
   directory rejects them. The original audio file stays untouched on
   disk; only the corpus copies and final output filenames use the
   sanitized name.
3. If the transcript is a Rev-style JSON: convert to a TextGrid via
   `scripts/json_to_textgrid.py` — one interval per monologue with
   `text` = concatenated word values, gaps between monologues become
   empty intervals, full duration from the audio file. If the JSON
   contains multiple speakers and the user has not pre-filtered,
   abort and tell the user to run `transcribe-en` to pick one speaker
   first. Example:
   ```bash
   python3 scripts/json_to_textgrid.py \
       --in    interview.JSON \
       --audio interview.wav \
       --out   interview.TextGrid
   ```
4. If the transcript is a plain `.txt`: only valid with backend
   `webmaus` (it sends the whole file to `runMAUSBasic` once). For
   `fave`, an utterance-level TextGrid is required — abort and ask
   the user to produce one.

### Step 1 — Convert audio to 16 kHz mono WAV

Both backends require 16 kHz mono. The `fave` path uses `sox`; the
`webmaus` path uses `ffmpeg` (called from inside `webmaus_align.py`).

```bash
# fave backend
sox "<input audio>" -r 16000 -c 1 /tmp/align_en_<basename>/<basename>_16k.wav

# webmaus backend
ffmpeg -y -i "<input audio>" -ar 16000 -ac 1 /tmp/align_en_<basename>/<basename>_16k.wav
```

### Step 2 — Branch on backend

#### Backend: `fave` (Montreal Forced Aligner)

1. Build the MFA corpus directory:
   ```bash
   mkdir -p /tmp/align_en_<basename>/corpus
   cp /tmp/align_en_<basename>/<basename>_16k.wav \
      /tmp/align_en_<basename>/corpus/<basename>.wav
   cp "<input.TextGrid>" \
      /tmp/align_en_<basename>/corpus/<basename>.TextGrid
   ```

2. Run MFA align:
   ```bash
   export MAMBA_ROOT_PREFIX=/tmp/micromamba
   /tmp/bin/micromamba run -n mfa mfa align \
     --single_speaker --clean --overwrite \
     /tmp/align_en_<basename>/corpus \
     english_us_arpa english_us_arpa \
     /tmp/align_en_<basename>/aligned
   ```

3. Verify the output TextGrid at
   `/tmp/align_en_<basename>/aligned/<basename>.TextGrid`. Print a count
   of word and phone intervals. OOV warnings can be reported but are not
   fatal — MFA's G2P handles them.

4. Final output: copy the MFA TextGrid to the directory of the original
   audio as `<basename>_aligned.TextGrid`.

#### Backend: `webmaus` (BAS WebMAUS API)

Run `scripts/webmaus_align.py`:

```bash
python3 "<this skill>/scripts/webmaus_align.py" \
  --audio "<input audio>" \
  --textgrid "<input TextGrid>" \
  --out "<output dir>"
```

(Or `--text "<input.txt>"` instead of `--textgrid` for plain-text input.)

What the script does:

1. Convert audio to 16 kHz mono WAV (ffmpeg).
2. Check BAS server load (`getLoadIndicator`); abort if 2 (full).
3. **TextGrid input:** for each non-empty interval, extract the chunk
   with ffmpeg and call `runMAUSBasic` with the chunk audio + chunk text
   (`LANGUAGE=eng-US`, `OUTFORMAT=TextGrid`). Sleep 0.5 s between calls.
   Shift the returned per-chunk ORT-MAU and MAU intervals back onto the
   full-recording timeline by adding the chunk's `xmin`.
   **Plain-text input:** call `runMAUSBasic` once with the full audio +
   full transcript.
4. Merge into a single TextGrid with three tiers: original transcription,
   `words` (renamed from ORT-MAU), and `phones` (renamed from MAU).
   Long text format, UTF-8.
5. Write to `<basename>_aligned.TextGrid` beside the original audio.

Read `references/textgrid-format.md` before running if the user supplies
their own TextGrid — WebMAUS is strict about encoding, tier name, empty
intervals, and minimum interval duration.

### Step 3 — Verify

Confirm the output TextGrid exists, is non-empty, and contains the
expected tiers (see Output table at the top). Print:

- Output path
- Number of word intervals (in `<spk> - words` or `words`)
- Number of phone intervals (in `<spk> - phones` or `phones`)
- Any chunks that failed (webmaus backend) or OOV words (fave backend)

### Step 4 — Cleanup

Remove `/tmp/align_en_<basename>/` unless the user asked to keep
intermediates.

## Notes

- **Data privacy (webmaus only):** uploaded data is deleted from BAS
  servers within 24 h, but it does leave the local machine. Use only
  with material you have consent to send externally.
- **Non-standard speech (webmaus):** the `eng-US` model is trained on
  General American. Strongly accented or dialectal speech may align
  imperfectly at the phone level; word-level `ORT-MAU` is still useful.
- **Citations:** if the user publishes results,
  - `webmaus`: cite Kisler T, Reichel U, Schiel F (2017). *Computer
    Speech and Language* 45, 326–347.
  - `fave`: cite the FAVE-Align / FAVE-extract toolkit (Rosenfelder et
    al.) and the english_us_arpa MFA model.

## Invocation

```
/align-en <audio> <transcript> --backend fave
/align-en <audio> <transcript> --backend webmaus
```

If `<transcript>` is omitted, look for a `.TextGrid` or `.json` of the
same basename in the audio's directory.
