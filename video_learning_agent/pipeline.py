from __future__ import annotations

from pathlib import Path

from .config import AgentConfig
from .jobs import JobStore
from .models import GpuProfile, JobStatus, VideoItem
from .remote_gpu import deploy_worker
from .resolver import read_tsv, resolve_url
from .subtitles import fetch_subtitles


def ingest(
    source: str,
    config: AgentConfig,
    gpu_profile: GpuProfile | None = None,
    batch_size: int = 20,
    asr_workers: int = 3,
    limit: int | None = None,
    skip_subtitles: bool = False,
) -> str:
    store = JobStore(config.jobs_root)
    path = Path(source)
    videos = read_tsv(path, limit=limit) if path.exists() else resolve_url(source, limit=limit)
    job_dir = store.create(videos)
    job_id = job_dir.name

    needs_asr: list[VideoItem] = []
    if not skip_subtitles:
        for item in videos:
            transcript = fetch_subtitles(item, job_dir / "captions")
            if transcript:
                item.needs_asr = False
                item.transcript_path = str(transcript)
                _copy_caption_transcript(transcript, job_dir / "transcripts" / item.video_id / "transcript.md")
            else:
                needs_asr.append(item)
    else:
        needs_asr = videos

    store.write_videos(job_id, videos)
    status = JobStatus(
        job_id=job_id,
        state="字幕完成" if not needs_asr else "等待 GPU ASR",
        total=len(videos),
        audio_done=len(videos) - len(needs_asr),
        transcript_done=len(videos) - len(needs_asr),
    )
    store.write_status(status)

    if needs_asr and gpu_profile:
        deploy_worker(
            gpu_profile,
            job_id,
            needs_asr,
            store,
            batch_size=batch_size,
            asr_workers=asr_workers,
        )
        status.state = "远程 ASR 已启动"
        store.write_status(status)
    return job_id


def _copy_caption_transcript(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

