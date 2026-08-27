from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .jobs import slugify
from .models import VideoItem


TIMESTAMP_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2}[,.]\d{3}\s+-->\s+")
TAG_RE = re.compile(r"<[^>]+>")


def fetch_subtitles(item: VideoItem, out_dir: Path) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = slugify(item.video_id or item.title)
    output = str(out_dir / f"{stem}.%(ext)s")
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        "zh.*,en.*",
        "--sub-format",
        "json3/vtt/srt",
        "--write-info-json",
        "-o",
        output,
        item.url,
    ]
    try:
        result = subprocess.run(cmd, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    candidates = sorted(out_dir.glob(f"{stem}.*"), key=lambda p: _caption_rank(p.name))
    for path in candidates:
        if path.suffix.lower() in {".json3", ".vtt", ".srt"}:
            transcript = normalize_caption(path, item)
            if transcript:
                target = out_dir / f"{stem}.transcript.md"
                target.write_text(transcript, encoding="utf-8")
                return target
    return None


def _caption_rank(name: str) -> tuple[int, str]:
    lowered = name.lower()
    if ".zh" in lowered or ".zh-" in lowered or ".zh_" in lowered:
        lang = 0
    elif ".en" in lowered:
        lang = 2
    else:
        lang = 4
    if lowered.endswith(".json3"):
        fmt = 0
    elif lowered.endswith(".vtt"):
        fmt = 1
    else:
        fmt = 2
    if "auto" in lowered:
        lang += 1
    return (lang + fmt, name)


def normalize_caption(path: Path, item: VideoItem) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json3":
        lines = _json3_lines(path)
    elif suffix == ".vtt":
        lines = _vtt_lines(path)
    elif suffix == ".srt":
        lines = _srt_lines(path)
    else:
        return ""
    lines = [line.strip() for line in lines if line.strip()]
    if not lines:
        return ""
    header = [
        f"# {item.title}",
        "",
        f"- URL: {item.url}",
        f"- ID: {item.video_id}",
        "- Source: subtitle",
        "",
        "## Transcript",
        "",
    ]
    return "\n".join(header + lines) + "\n"


def _json3_lines(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    lines: list[str] = []
    for event in data.get("events") or []:
        segs = event.get("segs") or []
        text = "".join(seg.get("utf8", "") for seg in segs)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            start = float(event.get("tStartMs") or 0) / 1000
            lines.append(f"[{_fmt_ts(start)}] {text}")
    return lines


def _vtt_lines(path: Path) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or "-->" in line or line.startswith(("NOTE", "Kind:", "Language:")):
            continue
        text = TAG_RE.sub("", line).strip()
        if text and text not in seen:
            seen.add(text)
            lines.append(text)
    return lines


def _srt_lines(path: Path) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.isdigit() or TIMESTAMP_RE.match(line):
            continue
        text = TAG_RE.sub("", line).strip()
        if text and text not in seen:
            seen.add(text)
            lines.append(text)
    return lines


def _fmt_ts(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

