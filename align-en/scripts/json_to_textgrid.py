#!/usr/bin/env python3
"""
json_to_textgrid.py — convert a Rev-style JSON transcript into an
utterance-level Praat TextGrid suitable for align-en input.

Usage:
    python3 json_to_textgrid.py \
        --in   interview.JSON \
        --audio interview.wav \
        --out  interview.TextGrid \
        --tier transcription

For each monologue in the JSON, produces one labeled interval covering
[first word ts, last word end_ts] with text = the concatenated text+punct
elements. Gaps between monologues are filled with empty intervals so the
tier is contiguous from 0 to the audio's duration.

Long text format, UTF-8.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def get_audio_duration(path: Path) -> float:
    out = subprocess.check_output([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ], text=True)
    return float(out.strip())


def monologue_text(elements: list[dict]) -> str:
    parts = []
    for e in elements:
        v = e.get("value", "")
        if not v:
            continue
        parts.append(v)
    return "".join(parts).strip()


def write_long_textgrid(out_path: Path, xmax: float, tier_name: str,
                        intervals: list[dict]) -> None:
    lines = [
        'File type = "ooTextFile"',
        'Object class = "TextGrid"',
        "",
        "xmin = 0",
        f"xmax = {xmax}",
        "tiers? <exists>",
        "size = 1",
        "item []:",
        "    item [1]:",
        '        class = "IntervalTier"',
        f'        name = "{tier_name}"',
        "        xmin = 0",
        f"        xmax = {xmax}",
        f"        intervals: size = {len(intervals)}",
    ]
    for i, iv in enumerate(intervals, 1):
        text = iv["text"].replace('"', '""')
        lines.append(f"        intervals [{i}]:")
        lines.append(f"            xmin = {iv['xmin']}")
        lines.append(f"            xmax = {iv['xmax']}")
        lines.append(f'            text = "{text}"')
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="Rev-style JSON → utterance TextGrid")
    p.add_argument("--in", dest="src", required=True, type=Path)
    p.add_argument("--audio", required=True, type=Path,
                   help="Audio file (used to determine xmax of the TextGrid)")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--tier", default="transcription",
                   help="Tier name in the output TextGrid (default: transcription)")
    p.add_argument("--snap-tol", type=float, default=0.001,
                   help="Snap together intervals separated by less than this (s)")
    args = p.parse_args()

    if not args.src.exists():
        sys.exit(f"input JSON not found: {args.src}")
    if not args.audio.exists():
        sys.exit(f"audio not found: {args.audio}")

    duration = get_audio_duration(args.audio)
    with open(args.src, encoding="utf-8") as f:
        data = json.load(f)

    monologues = data.get("monologues", [])
    speaker_ids = {m.get("speaker") for m in monologues if "speaker" in m}
    if len(speaker_ids) > 1:
        ids = ", ".join(str(s) for s in sorted(speaker_ids))
        sys.exit(
            f"input contains multiple speaker IDs ({ids}). align-en aligns "
            "one speaker at a time — pre-filter the JSON to a single speaker "
            "with transcribe-en/scripts/filter_speaker.py first."
        )

    raw: list[dict] = []
    for m in monologues:
        text_elems = [e for e in m["elements"]
                      if e.get("type") == "text" and "ts" in e and "end_ts" in e]
        if not text_elems:
            continue
        xmin = text_elems[0]["ts"]
        xmax = text_elems[-1]["end_ts"]
        text = monologue_text(m["elements"])
        if not text:
            continue
        raw.append({"xmin": float(xmin), "xmax": float(xmax), "text": text})

    if not raw:
        sys.exit("no usable monologues in JSON (need text elements with timestamps)")

    raw.sort(key=lambda iv: iv["xmin"])

    # Fill gaps with empty intervals; snap sub-millisecond touches together.
    out: list[dict] = []
    cursor = 0.0
    for iv in raw:
        start = iv["xmin"]
        end = min(iv["xmax"], duration)
        if abs(start - cursor) < args.snap_tol:
            start = cursor
        if start < cursor:
            # overlapping monologue — clip to cursor
            start = cursor
            if end <= start:
                continue
        if start > cursor:
            out.append({"xmin": cursor, "xmax": start, "text": ""})
        out.append({"xmin": start, "xmax": end, "text": iv["text"]})
        cursor = end
    if cursor < duration:
        out.append({"xmin": cursor, "xmax": duration, "text": ""})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_long_textgrid(args.out, duration, args.tier, out)

    n_labeled = sum(1 for iv in out if iv["text"])
    print(f"Wrote: {args.out}")
    print(f"  duration:  {duration:.2f} s")
    print(f"  intervals: {len(out)}  ({n_labeled} labeled, {len(out)-n_labeled} silence)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
