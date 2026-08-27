from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .models import VideoItem


BVID_RE = re.compile(r"(BV[0-9A-Za-z]+)")


def platform_for_url(url: str) -> str:
    lowered = url.lower()
    if "bilibili.com" in lowered or "b23.tv" in lowered:
        return "bilibili"
    if "youtube.com" in lowered or "youtu.be" in lowered:
        return "youtube"
    return "unknown"


def _run_ytdlp_json(url: str, flat: bool = True) -> dict | None:
    cmd = ["yt-dlp", "-J"]
    if flat:
        cmd.append("--flat-playlist")
    cmd.append(url)
    try:
        result = subprocess.run(cmd, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _item_from_entry(entry: dict, index: int, platform: str, fallback_url: str) -> VideoItem:
    video_id = str(entry.get("id") or entry.get("display_id") or "")
    url = str(entry.get("url") or entry.get("webpage_url") or fallback_url)
    if url and not url.startswith("http"):
        if platform == "youtube":
            url = f"https://www.youtube.com/watch?v={url}"
        elif platform == "bilibili":
            url = f"https://www.bilibili.com/video/{url}"
    return VideoItem(
        index=index,
        video_id=video_id or (BVID_RE.search(url).group(1) if BVID_RE.search(url) else f"video-{index}"),
        title=str(entry.get("title") or video_id or f"video-{index}"),
        url=url,
        duration=entry.get("duration"),
        platform=platform,
    )


def resolve_url(url: str, limit: int | None = None) -> list[VideoItem]:
    platform = platform_for_url(url)
    data = _run_ytdlp_json(url, flat=True)
    if data:
        entries = data.get("entries") or []
        if entries:
            videos = [_item_from_entry(e, i, platform, url) for i, e in enumerate(entries, 1) if e]
            return videos[:limit] if limit else videos
        return [_item_from_entry(data, 1, platform, url)]

    match = BVID_RE.search(url)
    video_id = match.group(1) if match else Path(url).stem or "video-1"
    return [VideoItem(index=1, video_id=video_id, title=video_id, url=url, platform=platform)]


def read_tsv(path: Path, limit: int | None = None) -> list[VideoItem]:
    import csv

    sample = path.read_text(encoding="utf-8-sig")[:4096]
    delimiter = "\t" if "\t" in sample else ","
    videos: list[VideoItem] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        for n, row in enumerate(reader, 1):
            if limit and len(videos) >= limit:
                break
            video_id = (row.get("bv") or row.get("BV") or row.get("id") or "").strip()
            url = (row.get("url") or "").strip()
            if not url and video_id.startswith("BV"):
                url = f"https://www.bilibili.com/video/{video_id}"
            if not url:
                continue
            detected_bv = BVID_RE.search(url)
            resolved_id = video_id or (detected_bv.group(1) if detected_bv else f"video-{n}")
            videos.append(
                VideoItem(
                    index=int(row.get("index") or n),
                    video_id=resolved_id,
                    title=(row.get("title") or video_id or f"video-{n}").strip(),
                    url=url,
                    duration=float(row["duration"]) if row.get("duration") else None,
                    platform=platform_for_url(url),
                )
            )
    return videos
