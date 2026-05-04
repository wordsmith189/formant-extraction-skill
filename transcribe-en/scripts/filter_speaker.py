#!/usr/bin/env python3
"""
filter_speaker.py — keep only one speaker's turns in a Rev-style JSON.

Usage:
    python3 filter_speaker.py --in interview_full.JSON --speaker 2 --out interview.JSON

Reads the unfiltered JSON written by transcribe_diarize.py, drops every
monologue whose `speaker` ID isn't the chosen one, sets
`selected_speaker` on the top-level object, and writes the result.

`speaker_map` is preserved verbatim — it's a record of who the diarizer
found, regardless of which one was chosen for analysis.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description="Filter a Rev-style JSON to a single speaker")
    p.add_argument("--in", dest="src", required=True, type=Path)
    p.add_argument("--speaker", required=True, type=int,
                   help="Speaker (cluster) ID to keep")
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()

    if not args.src.exists():
        sys.exit(f"input JSON not found: {args.src}")

    with open(args.src, encoding="utf-8") as f:
        data = json.load(f)

    speaker_map = data.get("speaker_map", {})
    if str(args.speaker) not in speaker_map:
        known = ", ".join(speaker_map.keys()) or "<none>"
        sys.exit(f"speaker {args.speaker} not in speaker_map (known: {known})")

    monologues = data.get("monologues", [])
    kept = [m for m in monologues if m.get("speaker") == args.speaker]
    dropped = len(monologues) - len(kept)

    out = {
        "speaker_map": speaker_map,
        "selected_speaker": str(args.speaker),
        "monologues": kept,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    n_text = sum(1 for m in kept for e in m["elements"] if e["type"] == "text")
    print(f"Wrote: {args.out}")
    print(f"  selected_speaker: {args.speaker} ({speaker_map[str(args.speaker)]})")
    print(f"  monologues kept:  {len(kept)}  (dropped {dropped})")
    print(f"  words in output:  {n_text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
