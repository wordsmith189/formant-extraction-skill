#!/usr/bin/env python3
"""
fave_to_csv.py — convert FAVE-extract output to the canonical vowel CSV.

Usage:
    python3 fave_to_csv.py \
        --fave-txt   <basename>_output.txt \
        --fave-norm  <basename>_output_norm.txt \
        --speaker    <speaker name> \
        --out        <basename>_vowels.csv

FAVE-extract writes one row per vowel with formant trajectories spread
across columns (F1@20%, F1@35%, F1@50%, F1@65%, F1@80% — and likewise for
F2). The canonical schema (see references/csv-schema.md) is one row per
(vowel, timepoint), so each FAVE row expands to five canonical rows.

F3, B1, B2, B3 are reported only once per vowel by FAVE (no per-timepoint
trajectory), so the same value is copied across all five rows. The
canonical columns come first; FAVE's other columns (Lobanov norms,
plotnik labels, etc.) follow as backend-specific extras.

Outlier flag (set on each row): F1 < 200 or > 1200, F2 < 500 or > 3500,
or vowel duration < 30 ms.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

CANONICAL_COLUMNS = [
    "vowel_label", "start", "end", "measurement_point_pct",
    "F1", "F2", "F3", "B1", "B2", "B3",
    "speaker", "word", "preceding_phone", "following_phone",
    "flag", "notes",
]

# FAVE columns that appear in the canonical 16-column block (and so should
# NOT be repeated in the extras block).
SUPPRESS_FROM_EXTRAS = {
    "vowel", "beg", "end", "F1", "F2", "F3", "B1", "B2", "B3",
    "word", "pre_seg", "fol_seg", "name",
    "F1@20%", "F2@20%", "F1@35%", "F2@35%",
    "F1@50%", "F2@50%", "F1@65%", "F2@65%",
    "F1@80%", "F2@80%",
}

POINTS = [20, 35, 50, 65, 80]


def read_fave_txt(path: Path) -> tuple[list[str], list[dict]]:
    """Return (fieldnames, rows) — fieldnames preserves the input column order."""
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        fieldnames = list(reader.fieldnames or [])
        return fieldnames, list(reader)


def read_norm_file(path: Path) -> list[dict]:
    """Parse FAVE's _norm.txt: line 1 = speaker info, line 2 = blank,
    line 3 = header, line 4+ = data."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) < 4:
        return []
    header = lines[2].split("\t")
    rows = []
    for line in lines[3:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        rows.append(dict(zip(header, parts)))
    return rows


def to_float(s: str) -> float | None:
    if s in ("", None, "NA", "nan", "NaN"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def is_outlier(F1: str, F2: str, dur_s: float | None) -> str:
    f1 = to_float(F1)
    f2 = to_float(F2)
    if f1 is not None and (f1 < 200 or f1 > 1200):
        return "outlier"
    if f2 is not None and (f2 < 500 or f2 > 3500):
        return "outlier"
    if dur_s is not None and dur_s < 0.030:
        return "outlier"
    return ""


def main() -> int:
    p = argparse.ArgumentParser(description="Convert FAVE-extract output to canonical CSV")
    p.add_argument("--fave-txt", required=True, type=Path)
    p.add_argument("--fave-norm", required=True, type=Path,
                   help="FAVE _norm.txt with Lobanov-normalized formants (optional but expected)")
    p.add_argument("--speaker", required=True)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()

    if not args.fave_txt.exists():
        sys.exit(f"FAVE .txt not found: {args.fave_txt}")

    fave_fieldnames, fave_rows = read_fave_txt(args.fave_txt)
    norm_rows = read_norm_file(args.fave_norm)
    if norm_rows and len(norm_rows) != len(fave_rows):
        print(f"WARN: row count mismatch (.txt={len(fave_rows)}, _norm={len(norm_rows)}); "
              "Lobanov values will be aligned by index where possible.",
              file=sys.stderr)

    extra_columns = [k for k in fave_fieldnames if k not in SUPPRESS_FROM_EXTRAS]

    fieldnames = CANONICAL_COLUMNS + ["F1_LobanovNormed_unscaled", "F2_LobanovNormed_unscaled"] + extra_columns

    out_rows = []
    for i, r in enumerate(fave_rows):
        beg = to_float(r.get("beg", ""))
        end = to_float(r.get("end", ""))
        dur = (end - beg) if (beg is not None and end is not None) else None

        norm = norm_rows[i] if i < len(norm_rows) else {}
        norm_F1 = norm.get("norm_F1", "")
        norm_F2 = norm.get("norm_F2", "")

        for pct in POINTS:
            F1 = r.get(f"F1@{pct}%", "")
            F2 = r.get(f"F2@{pct}%", "")
            F3 = r.get("F3", "")
            B1 = r.get("B1", "")
            B2 = r.get("B2", "")
            B3 = r.get("B3", "")

            row = {col: "" for col in fieldnames}
            row["vowel_label"] = r.get("vowel", "")
            row["start"] = r.get("beg", "")
            row["end"] = r.get("end", "")
            row["measurement_point_pct"] = pct
            row["F1"] = F1
            row["F2"] = F2
            row["F3"] = F3
            row["B1"] = B1
            row["B2"] = B2
            row["B3"] = B3
            row["speaker"] = args.speaker
            row["word"] = r.get("word", "")
            row["preceding_phone"] = r.get("pre_seg", "")
            row["following_phone"] = r.get("fol_seg", "")
            row["flag"] = is_outlier(F1, F2, dur)
            row["notes"] = ""
            row["F1_LobanovNormed_unscaled"] = norm_F1
            row["F2_LobanovNormed_unscaled"] = norm_F2
            for k in extra_columns:
                row[k] = r.get(k, "")
            out_rows.append(row)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)

    n_outlier = sum(1 for r in out_rows if r["flag"] == "outlier")
    print(f"\nWrote: {args.out}")
    print(f"  rows:     {len(out_rows)}  ({len(fave_rows)} vowels × 5 timepoints)")
    print(f"  outliers: {n_outlier}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
