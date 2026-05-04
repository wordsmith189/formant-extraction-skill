#!/usr/bin/env python3
"""
webmaus_align.py — force-align an English audio + transcript to word and
phone level using the BAS WebMAUS web service.

Usage:
    python3 webmaus_align.py --audio interview.wav --textgrid interview.TextGrid
    python3 webmaus_align.py --audio interview.wav --text interview.txt
    python3 webmaus_align.py --audio interview.wav --textgrid in.TextGrid --out /path/to/dir

Output:
    <basename>_aligned.TextGrid placed beside the audio file (or in --out if
    given). Long text format, UTF-8. Tiers: original transcription (verbatim
    from input TextGrid) + `words` (ORT-MAU renamed) + `phones` (MAU renamed,
    X-SAMPA labels).

TextGrid input mode:
    For each non-empty interval in the transcription tier, the script extracts
    that audio chunk with ffmpeg, sends it + its text to runMAUSBasic, and
    shifts the returned per-chunk intervals back onto the full-recording
    timeline. Empty intervals (silences, other-speaker turns, gaps) are not
    aligned and become empty intervals in the output.

Plain-text input mode:
    Sends the full audio + full transcript to runMAUSBasic in a single call.
    Best for short clips. The output's first tier is named "transcription"
    and contains a single interval covering the full recording.

Dependencies:
    pip3 install requests soundfile
    ffmpeg on PATH

Free for academic use. No API key. Uploaded data is deleted by BAS within 24h.
Cite: Kisler T, Reichel U, Schiel F (2017). Computer Speech and Language 45,
326-347.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
import soundfile as sf

LANGUAGE = "eng-US"
BASE_URL = "https://clarin.phonetik.uni-muenchen.de/BASWebServices/services"
LOAD_URL = f"{BASE_URL}/getLoadIndicator"
MAUSBASIC_URL = f"{BASE_URL}/runMAUSBasic"
SLEEP_BETWEEN_CHUNKS = 0.5
LOAD_RETRIES = 3
LOAD_RETRY_WAIT = 30


# ── TextGrid I/O ──────────────────────────────────────────────────────────────

def parse_textgrid(content: str) -> dict[str, list[dict]]:
    """Parse a TextGrid string into {tier_name: [interval_dicts]}.

    Handles long text format. Each interval dict has xmin, xmax, text.
    """
    tiers: dict[str, list[dict]] = {}
    tier_blocks = re.split(r"item \[\d+\]:", content)[1:]
    for block in tier_blocks:
        name_match = re.search(r'name = "(.*?)"', block)
        if not name_match:
            continue
        tier_name = name_match.group(1)
        intervals = []
        for m in re.finditer(
            r'xmin = ([\d.]+)\s+xmax = ([\d.]+)\s+text = "((?:[^"]*(?:"")?)*)"',
            block,
        ):
            intervals.append({
                "xmin": float(m.group(1)),
                "xmax": float(m.group(2)),
                "text": m.group(3),
            })
        tiers[tier_name] = intervals
    return tiers


def find_transcription_tier(tiers: dict[str, list[dict]]) -> tuple[str, list[dict]]:
    """Pick the transcription tier from a parsed TextGrid.

    Prefer a tier whose name starts with TRANSCRIPTION (case-insensitive),
    then any tier named "transcript", then the first tier in the file.
    """
    for name in tiers:
        if name.lower().startswith("transcription"):
            return name, tiers[name]
    for name in tiers:
        if name.lower() == "transcript":
            return name, tiers[name]
    name = next(iter(tiers))
    return name, tiers[name]


def write_long_textgrid(out_path: Path, xmax: float, tiers: list[tuple[str, list[dict]]]) -> None:
    """Write a long-format UTF-8 TextGrid.

    `tiers` is a list of (tier_name, intervals). Each intervals list must
    cover [0, xmax] contiguously — the caller is responsible for filling
    gaps with empty-text intervals.
    """
    lines = [
        'File type = "ooTextFile"',
        'Object class = "TextGrid"',
        "",
        "xmin = 0",
        f"xmax = {xmax}",
        "tiers? <exists>",
        f"size = {len(tiers)}",
        "item []:",
    ]
    for i, (name, intervals) in enumerate(tiers, 1):
        lines.append(f"    item [{i}]:")
        lines.append('        class = "IntervalTier"')
        lines.append(f'        name = "{name}"')
        lines.append("        xmin = 0")
        lines.append(f"        xmax = {xmax}")
        lines.append(f"        intervals: size = {len(intervals)}")
        for j, iv in enumerate(intervals, 1):
            text = iv["text"].replace('"', '""')
            lines.append(f"        intervals [{j}]:")
            lines.append(f"            xmin = {iv['xmin']}")
            lines.append(f"            xmax = {iv['xmax']}")
            lines.append(f'            text = "{text}"')
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fill_gaps(intervals: list[dict], xmax: float, snap_tol: float = 0.001) -> list[dict]:
    """Sort, deduplicate, and fill gaps with empty-text intervals.

    Adjacent intervals that touch within `snap_tol` seconds are snapped
    together to avoid sub-millisecond zero-width gaps.
    """
    if not intervals:
        return [{"xmin": 0.0, "xmax": xmax, "text": ""}]
    out: list[dict] = []
    cursor = 0.0
    for iv in sorted(intervals, key=lambda x: x["xmin"]):
        start = iv["xmin"]
        end = iv["xmax"]
        if abs(start - cursor) < snap_tol:
            start = cursor
        if start > cursor:
            out.append({"xmin": cursor, "xmax": start, "text": ""})
        out.append({"xmin": start, "xmax": end, "text": iv["text"]})
        cursor = end
    if cursor < xmax:
        out.append({"xmin": cursor, "xmax": xmax, "text": ""})
    return out


# ── Audio helpers ─────────────────────────────────────────────────────────────

def to_16k_mono_wav(src: Path, dst: Path) -> None:
    """Convert any audio file to 16 kHz mono WAV using ffmpeg."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-ar", "16000", "-ac", "1", str(dst)],
        check=True,
    )


def extract_chunk(src_wav: Path, start: float, end: float, dst: Path) -> None:
    """Extract [start, end] from src_wav into dst as 16 kHz mono."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src_wav),
         "-ss", f"{start:.6f}", "-to", f"{end:.6f}",
         "-ar", "16000", "-ac", "1", str(dst)],
        check=True,
    )


# ── BAS API ───────────────────────────────────────────────────────────────────

def check_load() -> int:
    """Returns 0 (low), 1 (medium), 2 (full), or -1 (unknown)."""
    try:
        r = requests.get(LOAD_URL, timeout=10)
        return int(r.text.strip())
    except Exception:
        return -1


def wait_for_load() -> int:
    """Block until BAS load is 0 or 1; abort on persistent 2 or persistent
    network failure. -1 means the load endpoint was unreachable; we retry
    rather than treat it as green."""
    load = -1
    for attempt in range(LOAD_RETRIES + 1):
        load = check_load()
        if 0 <= load < 2:
            return load
        if attempt < LOAD_RETRIES:
            if load == 2:
                msg = f"BAS server load=2 (full); waiting {LOAD_RETRY_WAIT}s..."
            else:
                msg = f"BAS load endpoint unreachable (status={load}); retrying in {LOAD_RETRY_WAIT}s..."
            print(msg, file=sys.stderr)
            time.sleep(LOAD_RETRY_WAIT)
    if load == 2:
        print("BAS server still full after retries. Aborting.", file=sys.stderr)
    else:
        print(f"BAS load endpoint still unreachable (status={load}). Aborting.", file=sys.stderr)
    sys.exit(1)


def get_download_link(response_bytes: bytes) -> str:
    root = ET.fromstring(response_bytes)
    success = root.find(".//success")
    if success is not None and success.text and success.text.strip().lower() == "false":
        output = root.find(".//output")
        msg = (output.text or "").strip() if output is not None else ""
        raise ValueError(f"BAS API error: {msg[:300]}")
    node = root.find(".//downloadLink")
    if node is None or not node.text:
        raise ValueError("No downloadLink in BAS response")
    return node.text


def call_mausbasic(wav_path: Path, text: str, timeout: int = 180) -> str:
    """Send (wav, text) to runMAUSBasic; return the output TextGrid as text."""
    text_file = io.BytesIO(text.encode("utf-8"))
    with open(wav_path, "rb") as wav_f:
        r = requests.post(
            MAUSBASIC_URL,
            files={
                "SIGNAL": (wav_path.name, wav_f, "audio/wav"),
                "TEXT": ("input.txt", text_file, "text/plain"),
            },
            data={"LANGUAGE": LANGUAGE, "OUTFORMAT": "TextGrid"},
            timeout=timeout,
        )
    r.raise_for_status()
    link = get_download_link(r.content)
    tg = requests.get(link, timeout=120)
    tg.raise_for_status()
    return tg.text


# ── Main alignment routines ───────────────────────────────────────────────────

def align_textgrid(audio: Path, textgrid: Path, workdir: Path) -> tuple[str, list[dict], list[dict], list[dict], float]:
    """Per-chunk alignment driven by a TextGrid transcription tier.

    Returns (transcription_tier_name, transcription_intervals, ort_mau_intervals,
    mau_intervals, audio_duration). Intervals are in the global timeline.
    """
    audio_16k = workdir / f"{audio.stem}_16k.wav"
    to_16k_mono_wav(audio, audio_16k)
    audio_duration = sf.info(str(audio_16k)).duration

    content = textgrid.read_text(encoding="utf-8")
    tiers = parse_textgrid(content)
    if not tiers:
        raise ValueError(f"No tiers parsed from {textgrid}")
    tier_name, intervals = find_transcription_tier(tiers)

    chunks = []
    for iv in intervals:
        text = iv["text"].strip()
        if not text:
            continue
        xmin = iv["xmin"]
        xmax = iv["xmax"]
        if xmax - xmin < 0.1:
            xmax = min(xmin + 0.1, audio_duration)
        chunks.append({"xmin": xmin, "xmax": xmax, "text": text})

    if not chunks:
        raise ValueError(f"No non-empty intervals in tier '{tier_name}'")

    print(f"Aligning {len(chunks)} chunks via runMAUSBasic ({LANGUAGE})...", file=sys.stderr)
    wait_for_load()

    ort_mau_all: list[dict] = []
    mau_all: list[dict] = []
    failures = []

    for i, chunk in enumerate(chunks, 1):
        chunk_wav = workdir / f"chunk_{i:04d}.wav"
        try:
            extract_chunk(audio_16k, chunk["xmin"], chunk["xmax"], chunk_wav)
            tg_text = call_mausbasic(chunk_wav, chunk["text"])
            chunk_tiers = parse_textgrid(tg_text)
            shift = chunk["xmin"]
            for tier_key, bucket in (("ORT-MAU", ort_mau_all), ("MAU", mau_all)):
                for iv in chunk_tiers.get(tier_key, []):
                    new_xmin = iv["xmin"] + shift
                    new_xmax = iv["xmax"] + shift
                    # Clamp to audio_duration: WebMAUS occasionally returns
                    # an xmax slightly past the chunk's end (sub-frame
                    # rounding); after shifting, that can overrun the full
                    # recording's duration and break TextGrid validation.
                    if new_xmin >= audio_duration:
                        continue
                    if new_xmax > audio_duration:
                        new_xmax = audio_duration
                    bucket.append({
                        "xmin": new_xmin,
                        "xmax": new_xmax,
                        "text": iv["text"],
                    })
        except Exception as e:
            failures.append((i, chunk["xmin"], chunk["xmax"], str(e)))
            print(f"  chunk {i} ({chunk['xmin']:.2f}-{chunk['xmax']:.2f}s) FAILED: {e}",
                  file=sys.stderr)
        finally:
            if chunk_wav.exists():
                chunk_wav.unlink()
        if i < len(chunks):
            time.sleep(SLEEP_BETWEEN_CHUNKS)

    if failures:
        print(f"\n{len(failures)} of {len(chunks)} chunks failed.", file=sys.stderr)

    transcription_intervals = [
        {"xmin": iv["xmin"], "xmax": iv["xmax"], "text": iv["text"].strip()}
        for iv in intervals if iv["text"].strip()
    ]
    return tier_name, transcription_intervals, ort_mau_all, mau_all, audio_duration


def align_plain_text(audio: Path, text_path: Path, workdir: Path) -> tuple[str, list[dict], list[dict], list[dict], float]:
    """One-shot alignment: send the entire recording + transcript to runMAUSBasic."""
    audio_16k = workdir / f"{audio.stem}_16k.wav"
    to_16k_mono_wav(audio, audio_16k)
    audio_duration = sf.info(str(audio_16k)).duration

    text = text_path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Empty transcript: {text_path}")

    print(f"Aligning full recording via runMAUSBasic ({LANGUAGE})...", file=sys.stderr)
    wait_for_load()
    tg_text = call_mausbasic(audio_16k, text, timeout=600)
    chunk_tiers = parse_textgrid(tg_text)

    transcription_intervals = [{"xmin": 0.0, "xmax": audio_duration, "text": text}]
    ort_mau = chunk_tiers.get("ORT-MAU", [])
    mau = chunk_tiers.get("MAU", [])
    return "transcription", transcription_intervals, ort_mau, mau, audio_duration


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description="WebMAUS English forced alignment")
    p.add_argument("--audio", required=True, type=Path, help="Input audio file (WAV or MP3)")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--textgrid", type=Path, help="Praat TextGrid with utterance tier")
    src.add_argument("--text", type=Path, help="Plain-text transcript (single recording)")
    p.add_argument("--out", type=Path, help="Output directory (default: beside the audio)")
    p.add_argument("--keep-tmp", action="store_true", help="Keep the /tmp working directory")
    args = p.parse_args()

    if not args.audio.exists():
        sys.exit(f"Audio not found: {args.audio}")
    if args.textgrid and not args.textgrid.exists():
        sys.exit(f"TextGrid not found: {args.textgrid}")
    if args.text and not args.text.exists():
        sys.exit(f"Text file not found: {args.text}")

    out_dir = args.out if args.out else args.audio.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.audio.stem}_aligned.TextGrid"

    workdir = Path(tempfile.mkdtemp(prefix=f"align_en_{args.audio.stem}_"))
    try:
        if args.textgrid:
            tier_name, trans, ort_mau, mau, duration = align_textgrid(
                args.audio, args.textgrid, workdir
            )
        else:
            tier_name, trans, ort_mau, mau, duration = align_plain_text(
                args.audio, args.text, workdir
            )

        write_long_textgrid(
            out_path,
            xmax=duration,
            tiers=[
                (tier_name, fill_gaps(trans, duration)),
                ("words", fill_gaps(ort_mau, duration)),
                ("phones", fill_gaps(mau, duration)),
            ],
        )

        print(f"\nWrote: {out_path}")
        print(f"  transcription intervals: {sum(1 for iv in trans if iv['text'].strip())}")
        print(f"  words intervals:         {len(ort_mau)}")
        print(f"  phones intervals:        {len(mau)}")
    finally:
        if not args.keep_tmp:
            subprocess.run(["rm", "-rf", str(workdir)], check=False)
        else:
            print(f"  workdir kept at:         {workdir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
