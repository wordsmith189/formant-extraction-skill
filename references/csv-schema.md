# Canonical vowel-formant CSV schema

Every CSV that `vowel-extract-en` writes must conform to this schema,
regardless of which extractor produced it. Downstream analysis code
(R / Python notebooks, plotting scripts) can rely on these column names
and types.

## Required columns (in order)

| #  | Column                | Type     | Description |
|----|-----------------------|----------|-------------|
| 1  | `vowel_label`         | string   | Vowel symbol from the source phone tier — ARPA (e.g. `AA`, `IH1`) for FAVE/MFA output, X-SAMPA (e.g. `i:`, `{`) for WebMAUS output. Stress digits kept where present. |
| 2  | `start`               | float    | Vowel-interval start time in seconds (full-recording timeline). |
| 3  | `end`                 | float    | Vowel-interval end time in seconds. |
| 4  | `measurement_point_pct` | int    | Percentage of the way through the vowel where formants were measured: 20, 35, 50, 65, or 80. One row per (vowel, point). |
| 5  | `F1`                  | float    | First formant in Hz at the measurement point. Empty if undefined. |
| 6  | `F2`                  | float    | Second formant in Hz. |
| 7  | `F3`                  | float    | Third formant in Hz. |
| 8  | `B1`                  | float    | Bandwidth of F1 in Hz. Empty if extractor doesn't report it (Praat extractor may leave blank). |
| 9  | `B2`                  | float    | Bandwidth of F2 in Hz. |
| 10 | `B3`                  | float    | Bandwidth of F3 in Hz. |
| 11 | `speaker`             | string   | Speaker identifier — usually the basename or a value lifted from the input TextGrid. |
| 12 | `word`                | string   | Word containing this vowel, from the words tier. Empty if not resolvable. |
| 13 | `preceding_phone`     | string   | Phone immediately before this vowel in the phones tier. Empty for the first phone of the recording. |
| 14 | `following_phone`     | string   | Phone immediately after. Empty for the last phone. |
| 15 | `flag`                | string   | `outlier` if the row tripped the outlier check (see below); empty otherwise. Reserved for future flag values; treat as a single-token string for now. |
| 16 | `notes`               | string   | Reserved for extractor messages in future versions (e.g. "F1 NA at 20%"). Always empty in v1 — neither extractor populates it yet. |

## Five rows per vowel

Each vowel produces five rows — one per measurement point at 20 %, 35 %,
50 %, 65 %, 80 % of the vowel duration. Frame-center bounds are used
for the percentage calculation (see the Praat extractor source) so the
20 % and 80 % points always have a defined formant value.

## Outlier flag

`flag = "outlier"` if **any** of these conditions hold for the row:

- `F1 < 200` Hz or `F1 > 1200` Hz
- `F2 < 500` Hz or `F2 > 3500` Hz
- `(end - start) < 0.030` s (vowel duration under 30 ms)

Outliers are flagged but **not removed** — downstream analysis can
filter on `flag != "outlier"`.

## Backend-specific extra columns

The FAVE extractor produces additional columns inherited from
FAVE-extract's native output. They appear **after** the canonical
columns above and are present in FAVE-extract CSVs only:

- `F1_LobanovNormed_unscaled`, `F2_LobanovNormed_unscaled` — Lobanov-
  normalized formants (FAVE's `_norm.txt`).
- `stress`, `vowel_index`, `pre_word`, `fol_word`, `pre_word_trans`,
  `word_trans`, `fol_word_trans` — FAVE context columns.
- `plt_vclass`, `plt_manner`, `plt_place`, `plt_voice`, `plt_preseg`,
  `plt_folseq`, `pre_seg`, `fol_seg`, `context` — Plotnik vowel-class
  and segmental-context labels.
- `nFormants` — number of formants tracked by FAVE.
- `t`, `dur`, `voicetype` — FAVE summary columns; partly redundant
  with the canonical columns.

The Praat extractor leaves all backend-specific extras out of its CSV.
Code that reads these CSVs should select columns by name, not by
position past column 16.
