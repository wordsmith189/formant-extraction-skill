#!/usr/bin/env python3
"""
run_praat_extractor.py — vowel-formant extraction via a headless Praat call.

Usage:
    python3 run_praat_extractor.py \
        --audio interview.wav \
        --textgrid interview_aligned.TextGrid \
        --speaker interview \
        --voice low \
        --out interview_vowels.csv

Detects the alignment backend from the TextGrid tier names:

  * tier names "words" + "phones" exactly  -> WebMAUS (X-SAMPA phone set)
  * tier names "<spk> - words" + "<spk> - phones" -> FAVE/MFA (ARPA phone set)

Reads the vowel inventory for the detected phone set from the repo's
references/vowel-sets.yaml (relative path: ../../references/vowel-sets.yaml).

Calls vowel-extract-en/scripts/extract_formants.praat to compute formants,
then post-processes the per-(vowel, timepoint) TSV into the canonical CSV
defined in references/csv-schema.md, applying the outlier flag.

Refuses to accept FAVE/MFA-style tier names without an explicit override
from the SKILL — see check_backend(). The "extractor=fave when input came
from webmaus" rejection happens in the calling SKILL, not here, because
this script *is* the praat path.

Dependencies:
    pip3 install pyyaml
    Praat installed and on PATH (or set --praat /path/to/praat)
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VOWEL_SETS = SKILL_ROOT / "references" / "vowel-sets.yaml"
PRAAT_SCRIPT = Path(__file__).resolve().parent / "extract_formants.praat"

CANONICAL_COLUMNS = [
    "vowel_label", "start", "end", "measurement_point_pct",
    "F1", "F2", "F3", "B1", "B2", "B3",
    "speaker", "word", "preceding_phone", "following_phone",
    "flag", "notes",
]


ARPA_LABEL_RE = re.compile(r"^[A-Z]+\d?$")


def parse_textgrid_tiers(path: Path) -> list[str]:
    """Return the list of tier names (in declaration order)."""
    content = path.read_text(encoding="utf-8")
    return re.findall(r'name = "(.*?)"', content)


def _phones_block_labels(content: str, phones_tier_idx: int) -> list[str]:
    """Return the non-empty `text = "..."` labels in the Nth tier block (0-based)."""
    blocks = re.split(r'item \[\d+\]:', content)[1:]
    if phones_tier_idx >= len(blocks):
        return []
    block = blocks[phones_tier_idx]
    labels = re.findall(r'text = "([^"]*)"', block)
    return [lab.strip() for lab in labels if lab.strip()]


def detect_backend(textgrid: Path) -> tuple[str, str, str]:
    """Return (phoneset, words_tier_name, phones_tier_name).

    phoneset is "arpa" (FAVE/MFA, ARPA labels with optional stress digits)
    or "xsampa" (WebMAUS, X-SAMPA labels).

    Detection order:
    1. `<spk> - words` / `<spk> - phones` (MFA without `--single_speaker`)
       → unambiguously FAVE/MFA → ARPA.
    2. Bare `words` / `phones` — could be either WebMAUS (after rename in
       webmaus_align.py) or MFA `--single_speaker`. Disambiguate by phone
       label content: if ≥ 80% of non-empty phone labels match the ARPA
       pattern `^[A-Z]+\\d?$` (e.g. `AA1`, `IH0`, `B`), it's ARPA;
       otherwise X-SAMPA.
    """
    content = textgrid.read_text(encoding="utf-8")
    tiers = re.findall(r'name = "(.*?)"', content)

    fave_phones = [t for t in tiers if re.match(r".+ - phones$", t)]
    fave_words = [t for t in tiers if re.match(r".+ - words$", t)]
    if fave_phones and fave_words:
        return "arpa", fave_words[0], fave_phones[0]

    if "phones" in tiers and "words" in tiers:
        labels = _phones_block_labels(content, tiers.index("phones"))
        if not labels:
            raise SystemExit(
                "ERROR: phones tier exists but contains no non-empty intervals.\n"
                "  Cannot infer phone set (ARPA vs X-SAMPA) without sample labels.\n"
                "  Likely cause: alignment failed silently. Re-run align-en and\n"
                "  inspect the aligned TextGrid in Praat before retrying."
            )
        arpa_share = sum(1 for lab in labels if ARPA_LABEL_RE.match(lab)) / len(labels)
        phoneset = "arpa" if arpa_share >= 0.8 else "xsampa"
        return phoneset, "words", "phones"

    raise SystemExit(
        "ERROR: TextGrid tier names don't match either supported backend.\n"
        f"  Found: {tiers}\n"
        "  Expected either ('words','phones') or ('<spk> - words','<spk> - phones')."
    )


def load_vowel_list(yaml_path: Path, phoneset: str) -> list[str]:
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if phoneset not in data:
        raise SystemExit(f"phoneset '{phoneset}' not found in {yaml_path}")
    section = data[phoneset]
    return list(section.get("monophthongs", []) or []) + list(section.get("diphthongs", []) or [])


def call_praat(praat_bin: str, audio: Path, textgrid: Path,
               words_tier: str, phones_tier: str,
               vowels_file: Path, max_formant: int, out_tsv: Path) -> None:
    cmd = [
        praat_bin, "--run", str(PRAAT_SCRIPT),
        str(audio), str(textgrid),
        words_tier, phones_tier,
        str(vowels_file), str(max_formant),
        str(out_tsv),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"Praat exited with code {proc.returncode}")
    if proc.stdout.strip():
        sys.stderr.write(proc.stdout)


def apply_outlier_flag(row: dict) -> str:
    """Return 'outlier' if any check trips, else ''."""
    def to_float(s):
        return float(s) if s not in ("", None) else None

    F1 = to_float(row.get("F1", ""))
    F2 = to_float(row.get("F2", ""))
    start = to_float(row.get("start", ""))
    end = to_float(row.get("end", ""))
    if F1 is not None and (F1 < 200 or F1 > 1200):
        return "outlier"
    if F2 is not None and (F2 < 500 or F2 > 3500):
        return "outlier"
    if start is not None and end is not None and (end - start) < 0.030:
        return "outlier"
    return ""


def main() -> int:
    p = argparse.ArgumentParser(description="Vowel formant extraction via headless Praat")
    p.add_argument("--audio", required=True, type=Path)
    p.add_argument("--textgrid", required=True, type=Path)
    p.add_argument("--speaker", default=None,
                   help="Speaker label written into every CSV row (default: audio stem)")
    p.add_argument("--voice", choices=("low", "high"), default="low",
                   help="low → max formant 5000 Hz; high → 5500 Hz")
    p.add_argument("--out", type=Path, default=None,
                   help="Output CSV path (default: <audio_stem>_vowels.csv beside the audio)")
    p.add_argument("--vowel-sets", type=Path, default=DEFAULT_VOWEL_SETS,
                   help=f"Path to vowel-sets.yaml (default: {DEFAULT_VOWEL_SETS})")
    p.add_argument("--praat", default="praat",
                   help="Praat binary to invoke (default: 'praat' on PATH)")
    args = p.parse_args()

    if not args.audio.exists():
        sys.exit(f"audio not found: {args.audio}")
    if not args.textgrid.exists():
        sys.exit(f"textgrid not found: {args.textgrid}")
    if not args.vowel_sets.exists():
        sys.exit(f"vowel-sets.yaml not found: {args.vowel_sets}")
    if shutil.which(args.praat) is None and not Path(args.praat).exists():
        sys.exit(f"praat binary not found: {args.praat}")
    if not PRAAT_SCRIPT.exists():
        sys.exit(f"praat script missing: {PRAAT_SCRIPT}")

    speaker = args.speaker or args.audio.stem
    out_path = args.out or args.audio.parent / f"{args.audio.stem}_vowels.csv"
    max_formant = 5000 if args.voice == "low" else 5500

    phoneset, words_tier, phones_tier = detect_backend(args.textgrid)
    print(f"Detected backend: {phoneset} (words='{words_tier}', phones='{phones_tier}')",
          file=sys.stderr)

    vowels = load_vowel_list(args.vowel_sets, phoneset)
    if not vowels:
        sys.exit(f"empty vowel list for phoneset {phoneset}")

    with tempfile.TemporaryDirectory(prefix="vowel_extract_en_") as tmpdir:
        tmp = Path(tmpdir)
        vowels_file = tmp / "vowels.txt"
        vowels_file.write_text("\n".join(vowels) + "\n", encoding="utf-8")
        praat_tsv = tmp / "praat_out.tsv"
        call_praat(args.praat, args.audio, args.textgrid,
                   words_tier, phones_tier,
                   vowels_file, max_formant, praat_tsv)

        with open(praat_tsv, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            raw_rows = list(reader)

    out_rows = []
    for r in raw_rows:
        canon = {col: "" for col in CANONICAL_COLUMNS}
        canon["vowel_label"] = r.get("vowel_label", "")
        canon["start"] = r.get("start", "")
        canon["end"] = r.get("end", "")
        canon["measurement_point_pct"] = r.get("measurement_point_pct", "")
        canon["F1"] = r.get("F1", "")
        canon["F2"] = r.get("F2", "")
        canon["F3"] = r.get("F3", "")
        canon["B1"] = r.get("B1", "")
        canon["B2"] = r.get("B2", "")
        canon["B3"] = r.get("B3", "")
        canon["speaker"] = speaker
        canon["word"] = r.get("word", "")
        canon["preceding_phone"] = r.get("preceding_phone", "")
        canon["following_phone"] = r.get("following_phone", "")
        canon["flag"] = apply_outlier_flag(r)
        canon["notes"] = ""
        out_rows.append(canon)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CANONICAL_COLUMNS)
        writer.writeheader()
        writer.writerows(out_rows)

    n_vowels = len({(r["start"], r["end"]) for r in out_rows})
    n_outlier = sum(1 for r in out_rows if r["flag"] == "outlier")
    print(f"\nWrote: {out_path}")
    print(f"  rows:     {len(out_rows)}  ({n_vowels} vowel intervals × 5 timepoints)")
    print(f"  outliers: {n_outlier}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
