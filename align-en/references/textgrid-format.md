# TextGrid Format Requirements for WebMAUS Input

## What WebMAUS Expects

When sending a Praat TextGrid as the transcript input (`runChunkPreparation`),
WebMAUS treats each labeled interval as a "chunk" — a segment of speech with
a known orthographic content and known time boundaries. It uses these to split
the alignment problem into manageable pieces before running MAUS on each chunk.

---

## Canonical Input TextGrid Structure

```
File type = "ooTextFile"
Object class = "TextGrid"

xmin = 0
xmax = 2847.3
tiers? <exists>
size = 2
item []:
    item [1]:
        class = "IntervalTier"
        name = "transcript"
        xmin = 0
        xmax = 2847.3
        intervals: size = 47
        intervals [1]:
            xmin = 0
            xmax = 3.42
            text = ""
        intervals [2]:
            xmin = 3.42
            xmax = 18.91
            text = "so when did you first move to Texas"
        intervals [3]:
            xmin = 18.91
            xmax = 19.50
            text = ""
        intervals [4]:
            xmin = 19.50
            xmax = 35.22
            text = "I moved here in nineteen eighty-two after finishing grad school"
        ...
    item [2]:
        class = "IntervalTier"
        name = "speaker"
        xmin = 0
        xmax = 2847.3
        intervals: size = 47
        intervals [1]:
            xmin = 0
            xmax = 3.42
            text = ""
        intervals [2]:
            xmin = 3.42
            xmax = 18.91
            text = "INT"
        ...
```

---

## Rule-by-Rule Specification

### R1 — File format: long text format only

Save from Praat as **"Save as text file..."** (not "Save as short text file...").

The file must begin with exactly:
```
File type = "ooTextFile"
Object class = "TextGrid"
```

Short text format (starts with `File type = "ooTextFile short"`) will be
rejected or misread by many parsers and is not recommended for archiving.

### R2 — Encoding: UTF-8

The file must be UTF-8 encoded. Praat's "Save as text file..." in version 6.x
writes UTF-8 by default. Older versions may write UTF-16 LE with BOM — check
with a hex editor or `file` command if you're unsure:

```bash
file interview_01.TextGrid
# should say: UTF-8 Unicode text
# NOT: Little-endian UTF-16 Unicode text
```

To convert UTF-16 to UTF-8:
```python
with open("file.TextGrid", encoding="utf-16") as f:
    content = f.read()
with open("file.TextGrid", "w", encoding="utf-8") as f:
    f.write(content)
```

### R3 — Filename: stem matches WAV, no special characters

- `interview_01.wav` → `interview_01.TextGrid` ✓
- `Interview 01.TextGrid` ✗ (space)
- `interview-01.TextGrid` ✗ (hyphen)
- `interview.01.TextGrid` ✗ (period)
- `interview_01_speaker_A.TextGrid` ✓

### R4 — At least one interval tier with transcript text

The transcript tier must be an `IntervalTier`, not a `TextTier` (point tier).
The tier name is whatever you'll pass as `tgitem` to `runChunkPreparation`.
Common names: `transcript`, `ortho`, `ORT`, `text`, `turns`, `speech`.

### R5 — Interval labels: clean orthographic words only

**DO include:**
- Plain spoken words in standard orthography
- Contractions: `it's`, `don't`, `y'all`
- Hyphenated compounds spoken as one unit: `eighty-two`
- Numbers as words: `nineteen eighty-two` (not `1982`)
  — OR leave as digits; WebMAUS will expand them internally

**DO NOT include in the transcript tier:**
- Speaker labels: `INT:` or `SP1:` — put these in a separate tier
- Timestamps or codes
- Annotation symbols: `[laughter]`, `{cough}`, `(unclear)` — use WebMAUS markers instead

**WebMAUS special markers (use these instead of custom symbols):**
- `<usb>` — unintelligible speech / unclear word(s)
- `<nib>` — non-speech noise (cough, laughter, door slam)

These must be separated from word tokens by spaces:
```
text = "yeah I <usb> don't know <nib> what you mean"
```

### R6 — Empty intervals: empty string `""`

Silences, pauses between turns, and non-speech regions **must** have:
```
text = ""
```

Not:
- `text = " "` (space — causes tokenization errors)
- `text = "-"` or `text = "..."` (treated as spoken words)
- `text = "<silence>"` (not a valid WebMAUS marker)

### R7 — Minimum interval duration: ≥ 100ms

MAUS cannot align intervals shorter than ~100ms. Short intervals labeled
with text will silently fail or produce garbage output. If you have very
short labeled intervals, either extend them or merge them with adjacent
speech.

Short empty intervals (< 50ms) are fine — they'll be passed through as silence.

### R8 — The `tgrate` parameter must match the WAV sample rate

When calling `runChunkPreparation`, the `tgrate` parameter must equal the
actual sampling rate of the `.wav` file in Hz. Common values: `16000`, `22050`,
`44100`, `48000`.

Detect programmatically:
```python
import soundfile as sf
info = sf.info("interview_01.wav")
tgrate = info.samplerate  # e.g. 16000
```

If `tgrate` is wrong, the chunk boundary times will be off by a constant
factor and alignment will fail.

### R9 — The `tgitem` parameter must match the tier name exactly

```python
tgitem = "transcript"  # must match name = "transcript" in the TextGrid exactly
```

Case-sensitive. If your tier is named `Transcript` (capital T), use that.

---

## Multi-Speaker Files

If you have two-speaker interview data:

**Option A — One tier per speaker (recommended)**

```
tiers: size = 2
  item [1]: IntervalTier "INT"      ← interviewer turns
  item [2]: IntervalTier "SP1"      ← subject turns
```

Run `runChunkPreparation` twice, once with `tgitem=INT` and once with `tgitem=SP1`,
then merge the resulting phone tiers afterward. The batch script handles this
automatically when `speaker_tiers` is set to a list.

**Option B — Single merged tier**

Merge both speakers into one tier. Speaker attribution is lost at the tier level
(can be tracked via a separate `speaker` tier). Simpler pipeline, less control.

---

## Pre-flight Validation Checklist

Run this Python snippet before submitting a batch to catch common errors:

```python
import tgt, soundfile as sf, os

def validate_pair(wav_path, tg_path, tier_name):
    errors = []

    # Check encoding
    try:
        with open(tg_path, encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        errors.append("NOT UTF-8 — likely UTF-16, needs conversion")
        return errors

    # Check format header
    if not content.startswith('File type = "ooTextFile"'):
        errors.append("Not long text format")

    # Load TextGrid
    tg = tgt.read_textgrid(tg_path)

    # Check tier exists
    tier_names = [t.name for t in tg.tiers]
    if tier_name not in tier_names:
        errors.append(f"Tier '{tier_name}' not found. Available: {tier_names}")
        return errors

    tier = tg.get_tier_by_name(tier_name)

    # Check for short intervals with text
    for interval in tier:
        if interval.text.strip() and (interval.end_time - interval.start_time) < 0.10:
            errors.append(
                f"Interval at {interval.start_time:.3f}s is <100ms but has label: '{interval.text}'"
            )

    # Check sample rate
    info = sf.info(wav_path)
    # (tgrate check deferred to caller — just report it)
    print(f"  Sample rate: {info.samplerate} Hz  (use as tgrate)")

    return errors

# Example usage:
for stem in stems:
    errs = validate_pair(f"audio/{stem}.wav", f"textgrids/{stem}.TextGrid", "transcript")
    if errs:
        print(f"ERRORS in {stem}: {errs}")
    else:
        print(f"OK: {stem}")
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `UnicodeDecodeError` on open | UTF-16 encoding | Convert to UTF-8 |
| `KeyError: tier not found` | `tgitem` name mismatch | Check exact tier name |
| Alignment wildly off | `tgrate` mismatch | Detect rate from WAV and fix |
| HTTP 400 from API | Interval has speaker label in text | Strip labels from transcript tier |
| Phone tier missing in output | All intervals were empty | Check that speech intervals have labels |
| Short intervals flagged | <100ms labeled intervals | Extend or merge those intervals |
| Server returns 503 | Load = 2, server overloaded | Check `getLoadIndicator`, wait and retry |
