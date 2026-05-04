#!/usr/bin/env python3
"""
transcribe_diarize.py — Whisper transcription + SpeechBrain ECAPA diarization.

Usage:
    python3 transcribe_diarize.py --audio interview.wav --out interview_full.JSON
    python3 transcribe_diarize.py --audio interview.wav --out out.JSON --n-speakers 2

Output: a Rev-style JSON containing all diarized speakers' turns (no
filtering). Each `monologues[i].speaker` is the cluster ID; `speaker_map`
labels each ID as "interviewer", "participant", or "extra speaker" via a
simple heuristic. `selected_speaker` is null — set by filter_speaker.py
after the user picks one.

Schema (matches Rev's API output):
    {
      "speaker_map":      {"0": "extra speaker", "1": "interviewer", "2": "participant"},
      "selected_speaker": null,
      "monologues": [
        {"speaker": 1, "elements": [
            {"type": "text", "value": "So", "ts": 0.99, "end_ts": 1.16, "confidence": 0.97},
            {"type": "punct", "value": " "},
            ...
            {"type": "punct", "value": "?"},
            {"type": "punct", "value": " "}
        ]},
        ...
      ]
    }

Disfluencies (uh, um, false starts, repetitions) are kept verbatim.

Dependencies:
    pip3 install faster-whisper speechbrain scikit-learn torchaudio numpy
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

import numpy as np
import torch
import torchaudio
from faster_whisper import WhisperModel
from sklearn.cluster import AgglomerativeClustering
from speechbrain.inference.speaker import SpeakerRecognition

warnings.filterwarnings("ignore", category=UserWarning)

DEFAULT_MODEL = "large-v3-turbo"
SR_TARGET = 16000
MIN_EMB_DURATION = 0.5
INTERVIEWER_WINDOW = 60.0
MAX_CHUNK_SEC = 1200.0  # 20 min — files longer than this are split first


def load_audio_mono_16k(path: Path) -> torch.Tensor:
    """Returns a 1-D tensor at 16 kHz."""
    waveform, sr = torchaudio.load(str(path))
    if waveform.size(0) > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    if sr != SR_TARGET:
        waveform = torchaudio.functional.resample(waveform, sr, SR_TARGET)
    return waveform.squeeze(0)


def get_audio_duration(path: Path) -> float:
    out = subprocess.check_output([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ], text=True)
    return float(out.strip())


def split_audio_if_needed(audio: Path, workdir: Path) -> list[tuple[Path, float]]:
    """If audio > 20 min, split into N equal chunks each <= 20 min.

    Returns a list of (chunk_path, start_offset_sec) in original-timeline order.
    Files at or under 20 min return [(audio, 0.0)] — no copy made.
    """
    duration = get_audio_duration(audio)
    if duration <= MAX_CHUNK_SEC:
        return [(audio, 0.0)]
    n_chunks = math.ceil(duration / MAX_CHUNK_SEC)
    chunk_len = duration / n_chunks
    print(f"Audio is {duration:.1f}s; splitting into {n_chunks} chunks of ~{chunk_len:.1f}s each",
          file=sys.stderr)
    chunks: list[tuple[Path, float]] = []
    suffix = audio.suffix
    for i in range(n_chunks):
        start = i * chunk_len
        end = (i + 1) * chunk_len if i < n_chunks - 1 else duration
        chunk_path = workdir / f"{audio.stem}_chunk{i+1:02d}{suffix}"
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(audio),
            "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
            "-c", "copy",
            str(chunk_path),
        ]
        subprocess.run(cmd, check=True)
        chunks.append((chunk_path, start))
    return chunks


def transcribe(audio: Path, model_size: str, cache_dir: Path,
               workdir: Path) -> list[dict]:
    """Transcribe audio. Splits files > 20 min into chunks, transcribes each,
    and merges segments with timestamps shifted onto the original timeline."""
    print(f"Loading faster-whisper model: {model_size}", file=sys.stderr)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    model = WhisperModel(
        model_size,
        device=device,
        compute_type=compute_type,
        download_root=str(cache_dir),
    )

    chunks = split_audio_if_needed(audio, workdir)
    out: list[dict] = []
    for i, (chunk_path, offset) in enumerate(chunks, 1):
        print(f"Transcribing chunk {i}/{len(chunks)}: {chunk_path.name} (offset {offset:.1f}s)...",
              file=sys.stderr)
        segments_iter, info = model.transcribe(
            str(chunk_path),
            language="en",
            word_timestamps=True,
            vad_filter=False,
        )
        for seg in segments_iter:
            words = []
            for w in (seg.words or []):
                ws = (w.start + offset) if w.start is not None else None
                we = (w.end + offset) if w.end is not None else None
                words.append({
                    "word": w.word,
                    "start": ws,
                    "end": we,
                    "probability": w.probability,
                })
            out.append({
                "start": seg.start + offset,
                "end": seg.end + offset,
                "text": seg.text.strip(),
                "words": words,
                "avg_logprob": seg.avg_logprob,
            })

    print(f"  {len(out)} segments total across {len(chunks)} chunk(s); "
          f"language={info.language} (p={info.language_probability:.2f})",
          file=sys.stderr)
    return out


def diarize(audio_tensor: torch.Tensor, segments: list[dict],
            n_speakers: int, cache_dir: Path) -> list[int]:
    """Cluster segments to speaker IDs. Returns a list aligned with segments."""
    print("Loading SpeechBrain ECAPA-TDNN...", file=sys.stderr)
    sb_dir = cache_dir / "speechbrain_ecapa"
    sb_dir.mkdir(parents=True, exist_ok=True)
    spk_model = SpeakerRecognition.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=str(sb_dir),
    )

    embeddings = []
    embeddable = []
    for i, seg in enumerate(segments):
        dur = seg["end"] - seg["start"]
        if dur < MIN_EMB_DURATION:
            continue
        s = max(int(seg["start"] * SR_TARGET), 0)
        e = min(int(seg["end"] * SR_TARGET), audio_tensor.size(0))
        if e - s < int(MIN_EMB_DURATION * SR_TARGET):
            continue
        chunk = audio_tensor[s:e].unsqueeze(0)  # (1, T)
        with torch.no_grad():
            emb = spk_model.encode_batch(chunk).squeeze().cpu().numpy()
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
        embeddings.append(emb)
        embeddable.append(i)

    if not embeddings:
        print("WARN: no segments long enough for embedding; assigning all to speaker 0",
              file=sys.stderr)
        return [0] * len(segments)

    X = np.vstack(embeddings)
    n_actual = min(n_speakers, X.shape[0])
    print(f"Clustering {X.shape[0]} embeddings into {n_actual} speakers...", file=sys.stderr)
    if n_actual == 1:
        labels_emb = np.zeros(X.shape[0], dtype=int)
    else:
        clustering = AgglomerativeClustering(
            n_clusters=n_actual, metric="cosine", linkage="average"
        )
        labels_emb = clustering.fit_predict(X)

    labels = [None] * len(segments)
    for idx_in_emb, seg_idx in enumerate(embeddable):
        labels[seg_idx] = int(labels_emb[idx_in_emb])

    # Fill short-segment gaps with the nearest valid label (prefer preceding).
    for i in range(len(labels)):
        if labels[i] is not None:
            continue
        chosen = None
        for j in range(i - 1, -1, -1):
            if labels[j] is not None:
                chosen = labels[j]
                break
        if chosen is None:
            for j in range(i + 1, len(labels)):
                if labels[j] is not None:
                    chosen = labels[j]
                    break
        labels[i] = int(chosen) if chosen is not None else 0

    return [int(x) for x in labels]


def assign_roles(segments: list[dict], cluster_ids: list[int]) -> dict[str, str]:
    """Heuristic role assignment.

    interviewer = cluster dominating speech in [0, 60s].
    participant = remaining cluster with the most total speech time.
    everything else = extra speaker.
    """
    early_time: dict[int, float] = {}
    total_time: dict[int, float] = {}
    for seg, cid in zip(segments, cluster_ids):
        dur = seg["end"] - seg["start"]
        total_time[cid] = total_time.get(cid, 0.0) + dur
        if seg["end"] <= INTERVIEWER_WINDOW:
            inc = dur
        elif seg["start"] < INTERVIEWER_WINDOW:
            inc = INTERVIEWER_WINDOW - seg["start"]
        else:
            inc = 0.0
        if inc > 0:
            early_time[cid] = early_time.get(cid, 0.0) + inc

    if early_time:
        interviewer = max(early_time, key=early_time.get)
    else:
        interviewer = max(total_time, key=total_time.get)

    remaining = {cid: t for cid, t in total_time.items() if cid != interviewer}
    if remaining:
        participant = max(remaining, key=remaining.get)
    else:
        participant = None

    speaker_map: dict[str, str] = {}
    for cid in total_time:
        if cid == interviewer:
            speaker_map[str(cid)] = "interviewer"
        elif cid == participant:
            speaker_map[str(cid)] = "participant"
        else:
            speaker_map[str(cid)] = "extra speaker"
    return speaker_map


def build_monologues(segments: list[dict], cluster_ids: list[int]) -> list[dict]:
    """Build Rev-style monologues, merging consecutive same-speaker segments."""
    monologues: list[dict] = []
    for seg, cid in zip(segments, cluster_ids):
        elements: list[dict] = []
        words = seg["words"]
        for i, w in enumerate(words):
            value = w["word"].strip() if w["word"] else ""
            if not value:
                continue
            entry: dict = {"type": "text", "value": value}
            if w.get("start") is not None:
                entry["ts"] = round(w["start"], 3)
                entry["end_ts"] = round(w["end"], 3)
            entry["confidence"] = round(w.get("probability") or 0.0, 2)
            elements.append(entry)
            if i < len(words) - 1:
                elements.append({"type": "punct", "value": " "})

        if elements:
            text = seg["text"].rstrip()
            if text.endswith("?"):
                punct = "?"
            elif text.endswith("!"):
                punct = "!"
            else:
                punct = "."
            elements.append({"type": "punct", "value": punct})
            elements.append({"type": "punct", "value": " "})

        if monologues and monologues[-1]["speaker"] == cid:
            monologues[-1]["elements"].extend(elements)
        else:
            monologues.append({"speaker": cid, "elements": elements})

    return monologues


def main() -> int:
    p = argparse.ArgumentParser(description="Whisper + diarization for English interviews")
    p.add_argument("--audio", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--n-speakers", type=int, default=3)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--cache-dir", type=Path, default=Path("/tmp/transcribe_en_cache"))
    args = p.parse_args()

    if not args.audio.exists():
        sys.exit(f"audio not found: {args.audio}")
    args.cache_dir.mkdir(parents=True, exist_ok=True)

    workdir = Path(tempfile.mkdtemp(prefix=f"transcribe_en_{args.audio.stem}_"))
    try:
        segments = transcribe(args.audio, args.model, args.cache_dir, workdir)
        if not segments:
            sys.exit("no segments transcribed")

        audio_tensor = load_audio_mono_16k(args.audio)
        cluster_ids = diarize(audio_tensor, segments, args.n_speakers, args.cache_dir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    speaker_map = assign_roles(segments, cluster_ids)
    monologues = build_monologues(segments, cluster_ids)

    output = {
        "speaker_map": speaker_map,
        "selected_speaker": None,
        "monologues": monologues,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    n_text = sum(1 for m in monologues for e in m["elements"] if e["type"] == "text")
    low_conf = sum(1 for m in monologues for e in m["elements"]
                   if e["type"] == "text" and e.get("confidence", 1.0) < 0.5)
    print(f"\nWrote: {args.out}")
    print(f"  monologues:        {len(monologues)}")
    print(f"  total words:       {n_text}")
    print(f"  low-confidence:    {low_conf}  (probability < 0.5)")
    print(f"  speaker_map:       {speaker_map}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
