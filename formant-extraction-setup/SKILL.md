---
name: formant-extraction-setup
description: >
  First-time setup for the formant-extraction toolkit. Detects OS and
  architecture, asks which pipeline path (lightweight WebMAUS+Praat or
  heavyweight FAVE/MFA) the user wants, checks what is already installed,
  installs missing dependencies by running the appropriate shell commands,
  creates the four skill symlinks under ~/.claude/skills/, and verifies the
  install. Use whenever the user asks to install or set up the
  formant-extraction toolkit, says something like "how do I get started",
  or when any sub-skill aborts because a dependency is missing. Also
  triggered by /formant-extraction-setup.
---

# formant-extraction-setup

Automates everything in `INSTALL.md`. Run this once before using
`formant-extraction`, `transcribe-en`, `align-en`, or `vowel-extract-en`.

---

## Step 0 — Detect environment

Run these three commands and store the results internally:

```bash
uname -s          # Darwin → macOS, Linux → Linux
uname -m          # arm64, x86_64
python3 --version # sanity check Python 3 is present
```

If `python3` is not found, print:

    Python 3 is required but was not found on PATH.
    Install it from https://www.python.org/downloads/ and re-run /formant-extraction-setup.

Then stop.

---

## Step 1 — Ask which path

Ask the user exactly this question (AskUserQuestion, two choices):

> **Which pipeline path do you want to install?**
>
> - **Lightweight** — WebMAUS (free BAS API, no local aligner) + headless Praat extractor. ~2 GB first time. Fast to install, good for most projects.
> - **Heavyweight** — Montreal Forced Aligner + FAVE-extract. ~5 GB first time, ~10 min install. Produces the canonical FAVE CSV used in published English-vowel studies.
>
> You can install the other path later by re-running /formant-extraction-setup.

Store the choice as `PATH` = `lightweight` or `heavyweight`.

---

## Step 2 — Detect what is already installed

Run all the checks silently (don't spam the user with every command).
Store a list of what is **missing**.

### Common (both paths)

| Dependency | Check command | Missing if… |
|---|---|---|
| ffmpeg | `which ffmpeg` | exits non-zero |
| Praat (headless) | `which praat` | exits non-zero |
| Python: requests | `python3 -c "import requests"` | exits non-zero |
| Python: soundfile | `python3 -c "import soundfile"` | exits non-zero |
| Python: pyyaml | `python3 -c "import yaml"` | exits non-zero |
| Python: numpy | `python3 -c "import numpy"` | exits non-zero |
| Python: faster-whisper | `python3 -c "import faster_whisper"` | exits non-zero |
| Python: speechbrain | `python3 -c "import speechbrain"` | exits non-zero |
| Python: scikit-learn | `python3 -c "import sklearn"` | exits non-zero |
| Python: torchaudio | `python3 -c "import torchaudio"` | exits non-zero |

### Heavyweight path only (skip these for lightweight)

| Dependency | Check command | Missing if… |
|---|---|---|
| micromamba binary | `test -f /tmp/bin/micromamba` | exits non-zero |
| MFA conda env | `/tmp/bin/micromamba env list 2>/dev/null \| grep -q "^mfa "` | exits non-zero |
| MFA acoustic model | `test -f ~/Documents/MFA/pretrained_models/acoustic/english_us_arpa.zip` | exits non-zero |
| MFA dictionary | `test -f ~/Documents/MFA/pretrained_models/dictionary/english_us_arpa.dict` | exits non-zero |
| Python: fave | `python3 -c "import fave"` | exits non-zero |
| sox | `which sox` | exits non-zero |

After checking, print a single summary to the user — ✓ for present,
✗ for missing:

    Checking dependencies…

      ✓ ffmpeg
      ✗ praat
      ✓ python: requests, soundfile, pyyaml, numpy
      ✗ python: faster-whisper, speechbrain, scikit-learn, torchaudio
      … (heavyweight only if relevant)

    Installing missing items now.

If **nothing is missing**, jump to Step 5 (symlinks).

---

## Step 3 — Install missing dependencies

Work through the missing list. Print each command before running it so
the user can see what is happening. Stop and report if any command fails
(non-zero exit) rather than plowing ahead.

### 3a — Python packages (both paths)

Collect all missing Python packages into one `pip3` call:

```bash
pip3 install --break-system-packages \
    requests soundfile pyyaml numpy \
    faster-whisper speechbrain scikit-learn torchaudio
```

(Only include packages that were flagged missing in Step 2.)

If `pip3` fails with a permissions error, retry with `--user`:

```bash
pip3 install --user \
    requests soundfile pyyaml numpy \
    faster-whisper speechbrain scikit-learn torchaudio
```

### 3b — ffmpeg

**macOS:**
```bash
brew install ffmpeg
```

**Linux:**
```bash
sudo apt-get update && sudo apt-get install -y ffmpeg
```

If `brew` is not found on macOS, print:

    Homebrew is not installed. Install it first:
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    Then re-run /formant-extraction-setup.

Then stop. Do not attempt to install Homebrew on the user's behalf — the
installer requires a sudo password prompt that Claude cannot satisfy.

### 3c — Praat (headless)

**macOS:**
```bash
brew install --cask praat
```

Note to user after install:

    Praat installed via Homebrew Cask. The headless binary is at
    /Applications/Praat.app/Contents/MacOS/Praat — the scripts call it
    via `praat --run`, which works without opening the GUI.

**Linux:** Print this message and stop:

    Linux users must build Praat from source for headless use.
    Instructions: https://www.fon.hum.uva.nl/praat/
    Once `praat` is on your PATH, re-run /formant-extraction-setup.

### 3d — sox (heavyweight path only)

**macOS:**
```bash
brew install sox
```

**Linux:**
```bash
sudo apt-get install -y sox
```

### 3e — micromamba + MFA conda env (heavyweight path only)

Only run if `micromamba` binary is missing.

**macOS arm64:**
```bash
curl -Ls https://micro.mamba.pm/api/micromamba/osx-arm64/latest \
    | tar -xvj -C /tmp bin/micromamba
```

**macOS x86_64:**
```bash
curl -Ls https://micro.mamba.pm/api/micromamba/osx-64/latest \
    | tar -xvj -C /tmp bin/micromamba
```

**Linux x86_64:**
```bash
curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest \
    | tar -xvj -C /tmp bin/micromamba
```

**Linux arm64:**
```bash
curl -Ls https://micro.mamba.pm/api/micromamba/linux-aarch64/latest \
    | tar -xvj -C /tmp bin/micromamba
```

Warn the user after downloading micromamba:

    micromamba is installed to /tmp/bin/micromamba.
    This path is wiped on reboot. Re-run /formant-extraction-setup
    after a restart to rebuild the MFA environment (~5–10 min).

### 3f — MFA conda env (heavyweight path only)

Only run if the `mfa` env is missing. This takes 5–10 min; tell the user
before starting:

    Building the MFA conda environment — this takes 5–10 min on first
    run and downloads ~1.5 GB. Grab a coffee.

```bash
export MAMBA_ROOT_PREFIX=/tmp/micromamba
/tmp/bin/micromamba create -n mfa -c conda-forge montreal-forced-aligner -y
```

### 3g — MFA acoustic model + dictionary (heavyweight path only)

Only run if models are missing:

```bash
export MAMBA_ROOT_PREFIX=/tmp/micromamba
/tmp/bin/micromamba run -n mfa mfa model download acoustic english_us_arpa
/tmp/bin/micromamba run -n mfa mfa model download dictionary english_us_arpa
```

### 3h — FAVE (heavyweight path only)

```bash
pip3 install --break-system-packages fave
```

If this fails with a permissions error, retry with `--user`.

---

## Step 4 — Post-install disk space note

After all installs, print an approximate footprint so the user is not
surprised:

**Lightweight:**

    Install complete. Approximate disk usage:
      Python deps (pip):           ~500 MB  (persistent)
      Whisper large-v3-turbo model: 1.5 GB  (cached in /tmp — re-downloads after reboot)
      SpeechBrain ECAPA-TDNN:      ~80 MB   (cached in /tmp)
      ffmpeg + Praat (Homebrew):   ~100 MB  (persistent)
      Total first run:             ~2 GB

**Heavyweight (add to lightweight total):**

    Additional heavyweight deps:
      micromamba binary:           14 MB    (/tmp — wiped on reboot)
      MFA conda env:               1.2 GB   (/tmp — wiped on reboot)
      MFA package cache:           1.5 GB   (safe to drop: micromamba clean -a)
      MFA pretrained models:       95 MB    (~/Documents/MFA — persistent)
      FAVE pip package:            ~50 MB   (persistent)
      Total first run:             ~5 GB

---

## Step 5 — Skill symlinks

Resolve the absolute path of the repo root. The setup skill lives at
`<repo>/formant-extraction-setup/SKILL.md`, so the repo root is two
levels up from `__file__` (or one level up from the skill folder).
Use:

```bash
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
```

Create the symlinks only if they don't already exist or are broken:

```bash
SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
mkdir -p "$SKILLS_DIR"

for skill in transcribe-en transcribe-bi align-en align-bi vowel-extract-en formant-extraction formant-extraction-setup; do
    target="$SKILLS_DIR/$skill"
    if [ -L "$target" ] && [ -e "$target" ]; then
        echo "  ✓ $skill  (already linked)"
    else
        ln -sfn "$REPO_ROOT/$skill" "$target"
        echo "  ✓ $skill  → $target"
    fi
done
```

Print the skill directory path at the end so the user knows where links
live.

---

## Step 6 — Verification

Run the appropriate checks for the chosen path.

### Both paths

```bash
which ffmpeg praat python3
python3 -c "import faster_whisper, speechbrain, sklearn, torchaudio; print('Python deps OK')"
python3 ~/.claude/skills/align-en/scripts/webmaus_align.py --help > /dev/null 2>&1 && echo "align-en OK"
```

### Heavyweight path only

```bash
export MAMBA_ROOT_PREFIX=/tmp/micromamba
/tmp/bin/micromamba run -n mfa mfa version
which fave-extract sox
```

Print a final pass/fail summary:

    Verification
      ffmpeg ............. ✓
      praat .............. ✓
      python deps ........ ✓
      align-en script .... ✓
      [heavyweight only:]
      mfa ................ ✓  (1.x.x)
      fave-extract ....... ✓
      sox ................ ✓

    All checks passed. You're ready to run /formant-extraction.

If any check fails, print which item failed and what command to retry,
then stop.

---

## Error handling rules

- **Any install command returns non-zero:** print the command, its
  stderr, and a one-line suggested fix. Do not continue to the next
  install step.
- **Homebrew not found on macOS:** print the manual install URL, then
  stop. Do not attempt to install Homebrew.
- **Linux + Praat:** print the build-from-source URL, then stop. This
  is a manual step.
- **`/tmp` is a ramdisk (Linux tmpfs with noexec):** the micromamba
  binary will fail to execute. Detect this with
  `mount | grep "/tmp"` and warn the user if `noexec` is set.

---

## Notes

- Re-running this skill is safe. All install commands are idempotent
  (pip and brew skip already-installed packages; symlinks are
  overwritten only if broken; conda env creation is skipped if the env
  already exists).
- To install both paths, run the skill twice — once for each.
- The `CLAUDE_SKILLS_DIR` environment variable overrides
  `~/.claude/skills/` as the symlink target, matching the convention
  in `formant-extraction/SKILL.md`.
- micromamba is intentionally installed to `/tmp` (ephemeral) rather
  than a permanent location, matching the pattern already documented in
  `INSTALL.md`. This keeps the tool from accumulating stale conda
  envs across upgrades.
