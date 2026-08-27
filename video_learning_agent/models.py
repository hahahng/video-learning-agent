from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class VideoItem:
    index: int
    video_id: str
    title: str
    url: str
    duration: float | None = None
    platform: str = "unknown"
    needs_asr: bool = True
    transcript_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VideoItem":
        return cls(
            index=int(data.get("index") or 0),
            video_id=str(data.get("video_id") or data.get("bv") or ""),
            title=str(data.get("title") or data.get("video_id") or "video"),
            url=str(data.get("url") or ""),
            duration=data.get("duration"),
            platform=str(data.get("platform") or "unknown"),
            needs_asr=bool(data.get("needs_asr", True)),
            transcript_path=data.get("transcript_path"),
        )


@dataclass
class GpuProfile:
    name: str
    host: str
    port: int
    user: str = "root"
    remote_root: str = "/root/autodl-tmp/video-learning-agent"
    password_env: str | None = None
    key_filename: str | None = None


@dataclass
class AgentConfig:
    jobs_root: Path = Path("work/jobs")
    data_root: Path = Path("data")
    gpu_profiles: dict[str, GpuProfile] = field(default_factory=dict)


@dataclass
class JobStatus:
    job_id: str
    state: str = "created"
    total: int = 0
    audio_done: int = 0
    transcript_done: int = 0
    current: str = ""
    audio_size: str = "0"
    free_disk: str = "unknown"
    gpu: str = "unknown"
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobStatus":
        fields = cls.__dataclass_fields__
        return cls(**{k: data[k] for k in fields if k in data})

