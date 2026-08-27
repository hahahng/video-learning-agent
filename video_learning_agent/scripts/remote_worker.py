#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def run(cmd: list[str]) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def safe_name(value: str) -> str:
    keep = []
    for char in value:
        if char.isalnum() or char in ("-", "_", ".", " "):
            keep.append(char)
        else:
            keep.append("-")
    return ("".join(keep).strip(" .-") or "video")[:120]


def read_items(path: Path) -> list[dict[str, str]]:
    sample = path.read_text(encoding="utf-8-sig")[:4096]
    delimiter = "\t" if "\t" in sample else ","
    items = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        for row in reader:
            url = (row.get("url") or "").strip()
            bv = (row.get("bv") or row.get("video_id") or row.get("id") or "").strip()
            if not url and bv.startswith("BV"):
                url = f"https://www.bilibili.com/video/{bv}"
            if not url:
                continue
            items.append(
                {
                    "index": row.get("index") or str(len(items) + 1),
                    "bv": bv,
                    "title": (row.get("title") or bv or url).strip(),
                    "url": url,
                }
            )
    return items


class Status:
    def __init__(self, job_id: str, total: int):
        self.data = {
            "job_id": job_id,
            "state": "starting",
            "total": total,
            "audio_done": 0,
            "transcript_done": 0,
            "current": "",
            "audio_size": "0",
            "free_disk": "unknown",
            "gpu": "unknown",
            "error": "",
        }

    def update(self, **kwargs) -> None:
        self.data.update(kwargs)
        self.data["audio_size"] = disk_usage("audio")
        self.data["free_disk"] = free_disk(".")
        self.data["gpu"] = gpu_status()
        text = json.dumps(self.data, ensure_ascii=False)
        Path("status.json").write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        with Path("status.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")


def disk_usage(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return "0"
    result = subprocess.run(["du", "-sh", path], check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return result.stdout.split()[0] if result.stdout.strip() else "0"


def free_disk(path: str) -> str:
    result = subprocess.run(["df", "-h", path], check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    lines = result.stdout.strip().splitlines()
    if len(lines) < 2:
        return "unknown"
    parts = lines[-1].split()
    return parts[3] if len(parts) >= 4 else "unknown"


def gpu_status() -> str:
    if not shutil.which("nvidia-smi"):
        return "no nvidia-smi"
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=utilization.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return "unavailable"
    first = result.stdout.strip().splitlines()[0]
    util, used, total = [x.strip() for x in first.split(",")[:3]]
    return f"{util}%，显存 {float(used)/1024:.1f}G / {float(total)/1024:.1f}G"


def have_gpu() -> bool:
    if not shutil.which("nvidia-smi"):
        return False
    result = subprocess.run(["nvidia-smi", "-L"], check=False, text=True, stdout=subprocess.PIPE)
    return result.returncode == 0 and "GPU" in result.stdout


def download_audio(item: dict[str, str], audio_dir: Path) -> Path:
    stem = safe_name(item["bv"] or item["title"])
    existing = [p for p in sorted(audio_dir.glob(f"{stem}.*")) if p.suffix not in {".part", ".ytdl"}]
    if existing:
        return existing[-1]
    run(["yt-dlp", "--no-playlist", "-f", "ba/bestaudio/best", "-o", str(audio_dir / f"{stem}.%(ext)s"), item["url"]])
    matches = [p for p in sorted(audio_dir.glob(f"{stem}.*")) if p.suffix not in {".part", ".ytdl"}]
    if not matches:
        raise FileNotFoundError(f"no audio downloaded for {item['url']}")
    return matches[-1]


def fmt_ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def write_transcript(item, segments, info, output_dir: Path, model_name: str) -> Path:
    stem = safe_name(item["bv"] or item["title"])
    video_dir = output_dir / stem
    video_dir.mkdir(parents=True, exist_ok=True)
    md_path = video_dir / "transcript.md"
    jsonl_path = video_dir / "segments.jsonl"
    with md_path.open("w", encoding="utf-8") as md, jsonl_path.open("w", encoding="utf-8") as js:
        md.write(f"# {item['title']}\n\n")
        md.write(f"- URL: {item['url']}\n")
        if item["bv"]:
            md.write(f"- BV: {item['bv']}\n")
        md.write(f"- Model: {model_name}\n- Device: cuda\n")
        md.write(f"- Detected language: {getattr(info, 'language', '')}\n\n## Transcript\n\n")
        for segment in segments:
            text = segment.text.strip()
            js.write(json.dumps({"start": segment.start, "end": segment.end, "text": text}, ensure_ascii=False) + "\n")
            md.write(f"[{fmt_ts(segment.start)} -> {fmt_ts(segment.end)}] {text}\n\n")
    return md_path


def transcribe_one(model, item, audio_path: Path, output_dir: Path, model_name: str) -> Path:
    segments, info = model.transcribe(str(audio_path), language="zh", vad_filter=True, beam_size=5)
    return write_transcript(item, segments, info, output_dir, model_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="videos.tsv")
    parser.add_argument("--model", default="medium")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--asr-workers", type=int, default=3)
    parser.add_argument("--audio-dir", default="audio")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--model-dir", default="models")
    args = parser.parse_args()

    from faster_whisper import WhisperModel

    Path("logs").mkdir(exist_ok=True)
    audio_dir = Path(args.audio_dir)
    output_dir = Path(args.output_dir)
    model_dir = Path(args.model_dir)
    for path in (audio_dir, output_dir, model_dir):
        path.mkdir(parents=True, exist_ok=True)

    items = read_items(Path(args.input))
    status = Status(job_id=Path.cwd().name, total=len(items))
    status.update(state="downloading")
    if not have_gpu():
        status.update(state="failed", error="CUDA requested but no GPU is visible")
        return 3

    audio_files: list[tuple[dict[str, str], Path]] = []
    for item in items:
        status.update(current=item["bv"] or item["title"], state="下载中")
        audio_files.append((item, download_audio(item, audio_dir)))
        status.update(audio_done=len(audio_files))

    status.update(state="加载模型")
    model = WhisperModel(args.model, device="cuda", compute_type="float16", download_root=str(model_dir))

    workers = max(1, min(args.asr_workers, len(audio_files)))
    status.update(state="ASR 中")
    completed = 0
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(transcribe_one, model, item, audio_path, output_dir, args.model): item
                for item, audio_path in audio_files
            }
            for future in as_completed(futures):
                item = futures[future]
                status.update(current=item["bv"] or item["title"])
                future.result()
                completed += 1
                status.update(transcript_done=completed)
    except RuntimeError as exc:
        if workers > 1 and ("CUDA" in str(exc) or "out of memory" in str(exc).lower()):
            status.update(state="ASR 中", error=f"并发 {workers} 失败，降级到 1: {exc}")
            completed = 0
            for item, audio_path in audio_files:
                status.update(current=item["bv"] or item["title"])
                transcribe_one(model, item, audio_path, output_dir, args.model)
                completed += 1
                status.update(transcript_done=completed)
        else:
            raise

    status.update(state="done", current="", error="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        data = {
            "job_id": Path.cwd().name,
            "state": "failed",
            "error": str(exc),
            "total": 0,
            "audio_done": 0,
            "transcript_done": 0,
            "current": "",
            "audio_size": disk_usage("audio"),
            "free_disk": free_disk("."),
            "gpu": gpu_status(),
        }
        Path("status.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"ERROR: {exc}", file=sys.stderr)
        raise

