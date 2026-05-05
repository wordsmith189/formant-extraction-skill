---
name: align-bi
description: >
  Force-align a bilingual interview recording with its language-tagged
  transcript at the word and phone level via the BAS WebMAUS API.
  Splits the transcript into per-language chunks (one WebMAUS call per
  monologue, with `LANGUAGE=<L1|L2>`), then merges all returned
  TextGrids back onto the original recording timeline. Phone labels
  default to X-SAMPA; pass `--phone-symbols ipa` to request IPA
  output instead (WebMAUS can emit either). FAVE/MFA is **not**
  available for bilingual data — there is no MFA acoustic model that
  spans two languages, so `align-bi` is WebMAUS-only by design. Use
  whenever the user asks to force-align a bilingual recording, or any
  recording the meta-skill is running with `--mode bilingual`.
---

# align-bi — bilingual forced alignment via WebMAUS

Force-align bilingual audio with its transcript at the word and phone
level. Unlike `align-en`, this skill has only one backend (WebMAUS),
because no off-the-shelf forced aligner has a single acoustic model
that handles two languages at once. The WebMAUS API is multilingual
in the sense that it accepts a `LANGUAGE` parameter per call — so the
strategy here is to send one call per monologue with the correct
language tag, then stitch the returned per-chunk TextGrids back into
one TextGrid that lives on the original recording timeline.

The output ends up beside the input audio.

## Why no FAVE backend?

FAVE/MFA aligns against a single language-specific acoustic model
(`english_us_arpa`, `spanish_mfa`, `mandarin_mfa`, etc.). Loading two
models for one TextGrid would mean re-running MFA per language with
its corpus split by language, then merging — which works in
principle but adds substantial install weight (one MFA acoustic
model + dictionary per language, ~500 MB each), produces label sets
that don't share an inventory (ARPA for English, IPA for the Spanish
MFA model, etc.), and breaks `vowel-extract`'s simple ARPA-vs-X-SAMPA
detector. WebMAUS gives the same per-language behavior in one HTTP
call, with one consistent label set across all languages, and no
local model install. For the bilingual path we accept the trade-off:
slightly less alignment accuracy than MFA in exchange for simplicity
and consistency.

If you have a strong reason to use MFA on bilingual data — e.g. you
have a bespoke acoustic model that spans both languages — the
recommended path is to bypass this skill and call MFA directly on
the per-language splits, then merge the TextGrids by hand. This
skill does not support that workflow.

## Output

A TextGrid with three tiers, in this order:

| Tier name        | Type     | Purpose |
|------------------|----------|---------|
| `transcription`  | interval | Original utterance-level transcription, one interval per monologue, language tag prefix in the label (e.g. `[L1] And then we moved...`). |
| `words`          | interval | One interval per aligned word. |
| `phones`         | interval | One interval per phone. **Default labels: X-SAMPA.** Switch to IPA via `--phone-symbols ipa`. |

A fourth optional tier is emitted if you pass `--keep-language-tier`:

| Tier name   | Type     | Purpose |
|-------------|----------|---------|
| `language`  | interval | One interval per monologue, label = `L1` or `L2`. Useful for downstream filtering by language. |

### Phone label sets

WebMAUS supports two output systems for phone labels and you choose
at the API level via the `OUTSYMBOL` parameter:

| `--phone-symbols` | WebMAUS `OUTSYMBOL` | Sample labels (Spanish) | Sample labels (English) |
|-------------------|---------------------|-------------------------|-------------------------|
| `xsampa` (default) | `sampa`             | `a`, `e`, `i`, `o`, `u`, `tS`, `B` | `i:`, `{`, `@`, `dZ` |
| `ipa`              | `ipa`               | `a`, `e`, `i`, `o`, `u`, `tʃ`, `β` | `iː`, `æ`, `ə`, `dʒ` |

**Default is X-SAMPA** because (a) it is the WebMAUS default, (b) the
existing `vowel-extract-en` Praat extractor's `vowel-sets.yaml` is
keyed on X-SAMPA symbols, and (c) X-SAMPA is ASCII so it is robust to
Praat-side encoding mishaps. Tell the user this up-front. If they ask
for IPA, switch to `--phone-symbols ipa` and warn them that
`vowel-extract-en` will need its `vowel-sets.yaml` extended (or use
the `ipa` inventory in the optional `--vowel-sets-ipa` reference) so
the Praat extractor recognizes IPA vowel symbols. Both label systems
are accepted by WebMAUS for every language WebMAUS supports — the
choice is purely a downstream convenience question.

## Inputs

| Argument | Notes |
|----------|-------|
| `--audio <path>` | Input recording. |
| `--json <path>`  | Rev-style JSON from `transcribe-bi` (with `language` field per monologue). |
| `--out-dir <path>` | Where to write `<basename>_aligned.TextGrid`. Defaults to the audio's directory. |
| `--phone-symbols xsampa\|ipa` | Phone-label system. Default `xsampa`. |
| `--keep-language-tier` | Emit the optional `language` tier (see Output). |

`align-bi` does not accept a plain `.txt` transcript or an
unsegmented TextGrid — both lose the language tags that WebMAUS needs
per chunk. Use `transcribe-bi` first to produce the language-tagged
JSON, or hand-build a JSON in the same shape.

## Prerequisites

Same as `align-en --backend webmaus`:

| Tool       | Check                                  | Install |
|------------|----------------------------------------|---------|
| Python 3   | `python3 --version`                    | system |
| ffmpeg     | `which ffmpeg`                         | `brew install ffmpeg` |
| requests   | `python3 -c "import requests"`         | `pip3 install requests` |
| soundfile  | `python3 -c "import soundfile"`        | `pip3 install soundfile` |
| Internet   | `curl -fsS https://clarin.phonetik.uni-muenchen.de/BASWebServices/services/getLoadIndicator` | — |

No micromamba, no MFA, no FAVE, no sox.

## Pipeline

Working directory: `/tmp/align_bi_<basename>/`. Cleaned up unless
`--keep-tmp` is passed.

### Step 0 — Validate and normalize inputs

1. Confirm the audio file exists.
2. **Sanitize the working basename** (drop extension, replace
   whitespace runs with single underscores). Same rule as
   `align-en` — even though FAVE/MFA isn't in this branch, the Praat
   extractor downstream still chokes on filenames with spaces.
3. Validate the JSON shape: must contain `languages.L1`,
   `languages.L2`, and a non-empty `monologues` list with at least
   one `language` field per monologue. Abort with a pointer to
   `transcribe-bi` if the JSON looks like a `transcribe-en` output
   without language tags.
4. Validate that `languages.L1.webmaus_code` and
   `languages.L2.webmaus_code` are in the WebMAUS supported-language
   list. If not, abort with the offending code and a link to the
   BAS web-services endpoint that lists supported languages.

### Step 1 — Convert audio to 16 kHz mono WAV

```bash
ffmpeg -y -i "<input audio>" -ar 16000 -ac 1 \
    /tmp/align_bi_<basename>/<basename>_16k.wav
```

WebMAUS requires 16 kHz mono. Same step as the WebMAUS branch of
`align-en`.

### Step 2 — Per-monologue alignment

Iterate through `monologues[]`. For each monologue:

1. Look up `webmaus_code = languages[ monologue.language ].webmaus_code`.
2. Determine the monologue's audio span:
   `start = monologue.elements[0].ts`,
   `end   = monologue.elements[-1].end_ts`.
3. Extract the chunk audio with ffmpeg:
   ```bash
   ffmpeg -y -i <basename>_16k.wav -ss <start> -to <end> \
       -ar 16000 -ac 1 \
       /tmp/align_bi_<basename>/chunks/m<NNNN>.wav
   ```
4. Concatenate the monologue's words into a chunk-local plain-text
   transcript:
   ```python
   text = " ".join(e["value"] for e in monologue["elements"]
                   if e["type"] == "text")
   ```
   Strip leading/trailing whitespace.
5. POST to `runMAUSBasic` with the chunk audio + chunk text:
   ```
   LANGUAGE   = <webmaus_code>
   OUTFORMAT  = TextGrid
   OUTSYMBOL  = sampa     # or 'ipa' if --phone-symbols ipa
   ```
6. Sleep 0.5 s between calls (BAS rate-limit etiquette).
7. Parse the returned TextGrid; **shift every interval's `xmin` /
   `xmax` by `+start`** so per-chunk intervals land on the original
   recording timeline.
8. Stash the shifted intervals in three lists keyed by tier name:
   `transcription`, `words` (renamed from `ORT-MAU`), `phones`
   (renamed from `MAU`).

If a chunk fails (HTTP error, BAS server load = 2 → "full", text
empty after stripping), record the failure in a list and continue.
Failed chunks become empty intervals on the output TextGrid so the
timeline stays aligned.

### Step 3 — Merge into one TextGrid

Build a long-format Praat TextGrid covering the full audio duration:

- `transcription` tier: one interval per monologue, label
  `"[L1] <text>"` or `"[L2] <text>"`. Empty intervals fill the gaps
  between monologues.
- `words` tier: all per-chunk word intervals concatenated, sorted by
  `xmin`. Gaps stay empty.
- `phones` tier: same, for phones.
- (Optional) `language` tier: one interval per monologue, label
  `L1` or `L2`.

Write UTF-8, long format, to:

```
<out_dir>/<basename>_aligned.TextGrid
```

### Step 4 — Verify

Print to the user:

    align-bi complete.
      aligned TextGrid: <path>
      tiers:            transcription, words, phones [, language]
      word intervals:   <N>
      phone intervals:  <M>
      phone label set:  <xsampa | ipa>
      L1 chunks:        <ok>/<total>     (<failed> failed)
      L2 chunks:        <ok>/<total>     (<failed> failed)

Then **stop**. The downstream gate (Gate 2 in the meta-skill) prompts
the user to open the TextGrid in Praat and verify the boundaries
before vowel extraction begins.

### Step 5 — Cleanup

Remove `/tmp/align_bi_<basename>/` unless `--keep-tmp` was passed.

## Telling the user what to expect

Before pressing Step 2, the meta-skill should surface this short
notice when `--mode bilingual` is in effect:

> Forced alignment for bilingual data uses the BAS WebMAUS API
> (the FAVE/MFA path is English-only). Phone labels will be in
> X-SAMPA by default — that's the WebMAUS default, and what the
> Praat vowel extractor's symbol inventory expects. If you'd
> rather have IPA labels, say so and I'll re-run alignment with
> `--phone-symbols ipa`. WebMAUS supports both label systems for
> every language it covers; the choice is purely a downstream
> convenience question.

If the user opts for IPA, also remind them at this point that the
Praat vowel extractor will need an IPA-keyed `vowel-sets.yaml` (the
shipped inventory only covers ARPA and X-SAMPA).

## Notes

- **Data privacy:** uploaded data is deleted from BAS servers within
  24 h, but it does leave the local machine. Use only with material
  the user has consent to send externally.
- **Non-standard speech:** the WebMAUS `*-US` / `*-MX` / `*-CN` etc.
  acoustic models are trained on standardized varieties. Strong
  regional dialects, sociolects, or heavily accented L2 speech will
  align imperfectly at the phone level. Word-level alignment is
  usually still usable.
- **Mid-monologue switches** are not handled — see `transcribe-bi` →
  *Known limitations*. If a single English word appears inside an
  otherwise-Spanish monologue, the whole monologue is sent to WebMAUS
  with `LANGUAGE=spa-MX`, and the English word is force-aligned
  against the Spanish phone inventory (usually with bad phone-level
  results, though word boundaries often survive).
- **Citation:** if the user publishes results from this path, cite
  Schiel (1999) and Kisler, Reichel & Schiel (2017) — see the
  toolkit `README.md` → "Citing FAVE and WebMAUS".

## Invocation

```
/align-bi <audio> --json <transcript.JSON> [--phone-symbols xsampa|ipa] [--keep-language-tier]
```

If `--json` is omitted, look for `<basename>.JSON` next to the
audio. If that JSON is missing the `language` field on monologues,
abort with a pointer to `/transcribe-bi`.
