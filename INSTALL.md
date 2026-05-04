# Install

> **Recommended:** if you already have the skills symlinked into
> `~/.claude/skills/`, just run `/formant-extraction-setup` in Claude and
> it will handle everything on this page automatically — OS detection,
> dependency installs, symlinks, and verification. The manual steps below
> are a reference for CI environments, troubleshooting, or users who
> prefer to install by hand.

The toolkit ships two parallel paths through the alignment + extraction
stages. Pick one. The lightweight path is faster to install, easier to
maintain, and good enough for most research; the heavyweight path produces
the canonical FAVE-extract CSV that many published English-vowel studies
have used.

## Lightweight (recommended for most users)

WebMAUS for alignment + a Praat script for vowel extraction. Everything
runs locally except the alignment HTTP calls to BAS WebMAUS (free for
academic use, no key, data deleted within 24 h).

```bash
pip3 install requests soundfile pyyaml numpy \
    faster-whisper speechbrain scikit-learn torchaudio
# macOS:
brew install ffmpeg
brew install --cask praat              # Praat ships in homebrew-cask, not core
# Linux:
# apt install ffmpeg
# (build praat from source — see https://www.fon.hum.uva.nl/praat/)
```

`sox` is only needed for the heavyweight (FAVE/MFA) path — `align-en
--backend webmaus` uses `ffmpeg` for both resampling and chunk
extraction.

That's it. No micromamba, no MFA, no FAVE. Skill flags:

```text
align-en       --backend webmaus
vowel-extract-en --extractor praat
```

## Heavyweight (FAVE/MFA path)

Montreal Forced Aligner for alignment + FAVE-extract for formants. Heavy
install via micromamba; on first run MFA also downloads its acoustic
model and dictionary (~500 MB).

```bash
# 1. micromamba
curl -Ls https://micro.mamba.pm/api/micromamba/osx-arm64/latest \
  | tar -xvj -C /tmp bin/micromamba

# 2. MFA (in a micromamba env)
export MAMBA_ROOT_PREFIX=/tmp/micromamba
/tmp/bin/micromamba create -n mfa -c conda-forge montreal-forced-aligner -y
/tmp/bin/micromamba run -n mfa mfa model download acoustic english_us_arpa
/tmp/bin/micromamba run -n mfa mfa model download dictionary english_us_arpa

# 3. FAVE-extract (Python pip)
pip3 install --user fave

# 4. Praat (headless wrapper) and sox
brew install --cask praat              # macOS; Linux: build praat from source
brew install sox                       # macOS; Linux: apt install sox
# (See vowel-extract-en/SKILL.md "Step 1 — Praat wrapper for headless FAVE"
#  for the wrapper shim that lets FAVE-extract call Praat without a GUI.)
```

Skill flags:

```text
align-en       --backend fave
vowel-extract-en --extractor fave
```

## Installing the skills

Symlink each sub-folder into `~/.claude/skills/`:

```bash
ln -s "$(pwd)/transcribe-en"      ~/.claude/skills/transcribe-en
ln -s "$(pwd)/align-en"           ~/.claude/skills/align-en
ln -s "$(pwd)/vowel-extract-en"   ~/.claude/skills/vowel-extract-en
ln -s "$(pwd)/formant-extraction" ~/.claude/skills/formant-extraction
```

Each sub-skill stands on its own — install only the ones you need.

## Verifying

```bash
# lightweight path
python3 align-en/scripts/webmaus_align.py --help
which praat ffmpeg

# heavyweight path
export MAMBA_ROOT_PREFIX=/tmp/micromamba
/tmp/bin/micromamba run -n mfa mfa version
which fave-extract sox
```

## Disk space

Measured on macOS (Apple Silicon, May 2026). Sizes are approximate;
caches grow with use.

### Lightweight path (WebMAUS)

- Python deps (`requests`, `soundfile`, `pyyaml`, `faster-whisper`, `speechbrain`, `scikit-learn`, `torchaudio`): ~500 MB, persistent in `~/Library/Python/3.x/`.
- Whisper `large-v3-turbo` model: 1.5 GB, cached under `/tmp/transcribe_en_cache/`; re-downloads on `/tmp` wipe.
- SpeechBrain ECAPA-TDNN: ~80 MB, cached alongside Whisper.
- **Total first-time: ≈ 2 GB**. Drops to ~500 MB persistent after `/tmp` wipe; re-warming costs ~5 min of network.

Plus ~100 MB for ffmpeg + sox + Praat via Homebrew if not already installed.

### Heavyweight path (FAVE/MFA)

Adds the lightweight footprint above, plus:

- micromamba binary: 14 MB at `/tmp/bin/micromamba`; wiped on reboot.
- MFA conda env: 1.2 GB at `/tmp/micromamba/envs/mfa`; wiped on reboot.
- MFA package cache: 1.5 GB at `/tmp/micromamba/pkgs`; safe to drop with `micromamba clean -a` after the env is built.
- MFA pretrained models (acoustic + dict): 95 MB at `~/Documents/MFA/pretrained_models/`; persistent.
- FAVE pip package: ~50 MB; persistent.
- **Total first-time: ≈ 5 GB**. Drops to **~3.5 GB** after `micromamba clean -a`.

After a `/tmp` wipe (machine reboot) the heavy path persists ~1.6 GB
(MFA models + Python deps). Re-bootstrapping the conda env takes
~5–10 min of network.

### Per-recording transient files

For each recording you process, the pipeline writes intermediates under
`/tmp/`. These are cleaned up at the end of each run unless you pass
`--keep-tmp`. Rough sizes per minute of audio:

- 16 kHz mono WAV (one copy): ~2 MB / min
- MFA corpus dir (one copy of audio + textgrid): ~2 MB / min
- WebMAUS chunked WAVs (per-utterance): negligible (deleted after each API call)
- FAVE-extract `.txt` / `_norm.txt`: < 1 MB total per recording
