from __future__ import annotations

import json
from pathlib import Path

from .config import load_config, profile_for_cli
from .digest import write_digests
from .jobs import JobStore
from .pipeline import ingest
from .remote_gpu import pull_remote_outputs, read_remote_status
from .search import search_index


def main() -> None:
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore
    except ModuleNotFoundError as exc:
        raise SystemExit("MCP SDK is required. Install with: pip install '.[mcp]'") from exc

    mcp = FastMCP("video-learning-agent")
    config = load_config()
    store = JobStore(config.jobs_root)

    @mcp.tool()
    def ingest_url(source: str, gpu_profile: str | None = None, limit: int | None = None) -> str:
        profile = profile_for_cli(config, gpu_profile, None, None, None, None, None) if gpu_profile else None
        job_id = ingest(source, config, gpu_profile=profile, limit=limit)
        return json.dumps({"job_id": job_id, "status": store.read_status(job_id).to_dict()}, ensure_ascii=False)

    @mcp.tool()
    def job_status(job_id: str, gpu_profile: str | None = None) -> str:
        if gpu_profile:
            profile = profile_for_cli(config, gpu_profile, None, None, None, None, None)
            status = read_remote_status(profile, job_id, store)
        else:
            status = store.read_status(job_id)
        return json.dumps(status.to_dict(), ensure_ascii=False)

    @mcp.tool()
    def run_remote_asr(job_id: str, gpu_profile: str, batch_size: int = 20, asr_workers: int = 3) -> str:
        from .remote_gpu import deploy_worker

        profile = profile_for_cli(config, gpu_profile, None, None, None, None, None)
        videos = [item for item in store.read_videos(job_id) if item.needs_asr]
        meta = deploy_worker(profile, job_id, videos, store, batch_size=batch_size, asr_workers=asr_workers)
        return json.dumps(meta, ensure_ascii=False)

    @mcp.tool()
    def pull_transcripts(job_id: str, gpu_profile: str) -> str:
        profile = profile_for_cli(config, gpu_profile, None, None, None, None, None)
        copied = pull_remote_outputs(profile, job_id, store)
        return json.dumps({"job_id": job_id, "copied": copied}, ensure_ascii=False)

    @mcp.tool()
    def digest_transcripts(job_id: str, use_llm: bool = True) -> str:
        job_dir = store.job_dir(job_id)
        written = write_digests(job_dir / "transcripts", job_dir / "digests", use_llm=use_llm)
        return json.dumps({"job_id": job_id, "written": [str(p) for p in written]}, ensure_ascii=False)

    @mcp.tool()
    def search_notes(query: str, db: str = "data/video_learning.sqlite", top_k: int = 8) -> str:
        return json.dumps(search_index(query, Path(db), top_k=top_k), ensure_ascii=False)

    mcp.run()


if __name__ == "__main__":
    main()
