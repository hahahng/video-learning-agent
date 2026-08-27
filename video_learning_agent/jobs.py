from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .models import JobStatus, VideoItem


def slugify(value: str, limit: int = 80) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "-", value).strip(".-_")
    return (cleaned or "video")[:limit]


def new_job_id(prefix: str = "job") -> str:
    return f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}"


class JobStore:
    def __init__(self, jobs_root: Path):
        self.jobs_root = jobs_root
        self.jobs_root.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        return self.jobs_root / job_id

    def create(self, videos: list[VideoItem], job_id: str | None = None) -> Path:
        job_id = job_id or new_job_id("video")
        root = self.job_dir(job_id)
        for sub in ("transcripts", "digests", "logs", "captions"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        self.write_videos(job_id, videos)
        self.write_status(JobStatus(job_id=job_id, total=len(videos)))
        (root / "job.json").write_text(
            json.dumps({"job_id": job_id, "created_at": time.time()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return root

    def write_videos(self, job_id: str, videos: list[VideoItem]) -> None:
        path = self.job_dir(job_id) / "videos.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for item in videos:
                handle.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")

    def read_videos(self, job_id: str) -> list[VideoItem]:
        path = self.job_dir(job_id) / "videos.jsonl"
        return [VideoItem.from_dict(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def write_status(self, status: JobStatus) -> None:
        path = self.job_dir(status.job_id) / "status.json"
        path.write_text(json.dumps(status.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def read_status(self, job_id: str) -> JobStatus:
        path = self.job_dir(job_id) / "status.json"
        if not path.exists():
            return JobStatus(job_id=job_id, state="missing")
        return JobStatus.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def write_tsv(self, job_id: str, videos: list[VideoItem]) -> Path:
        path = self.job_dir(job_id) / "videos.tsv"
        with path.open("w", encoding="utf-8") as handle:
            handle.write("index\tbv\ttitle\turl\tduration\n")
            for item in videos:
                handle.write(
                    f"{item.index}\t{item.video_id}\t{item.title}\t{item.url}\t{item.duration or ''}\n"
                )
        return path


def format_status(status: JobStatus) -> str:
    return "\n".join(
        [
            f"进度：{status.state}",
            f"音频：{status.audio_done} / {status.total}",
            f"转写：{status.transcript_done} / {status.total}",
            f"当前：{status.current or '-'}",
            f"GPU：{status.gpu}",
            f"音频占用：{status.audio_size}",
            f"数据盘剩余：{status.free_disk}",
            f"错误：{status.error or '无'}",
        ]
    )

