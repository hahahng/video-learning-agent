from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .config import load_config, profile_for_cli
from .digest import write_digests
from .jobs import JobStore, format_status
from .pipeline import ingest
from .remote_gpu import RemoteGpuError, pull_remote_outputs, read_remote_status, watch_status
from .search import build_index, search_index, snippet
from .vector_store import build_chroma_index, query_chroma


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="video-agent", description="Video Learning Agent")
    parser.add_argument("--config", default=None, help="Path to video-agent config yaml/json")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest_p = sub.add_parser("ingest", help="Resolve URL/list, fetch subtitles, and optionally launch remote GPU ASR")
    ingest_p.add_argument("source", help="Bilibili/YouTube URL or local TSV/CSV")
    ingest_p.add_argument("--gpu-profile")
    ingest_p.add_argument("--host")
    ingest_p.add_argument("--port", type=int)
    ingest_p.add_argument("--user", default="root")
    ingest_p.add_argument("--password-env")
    ingest_p.add_argument("--key-filename")
    ingest_p.add_argument("--batch-size", type=int, default=20)
    ingest_p.add_argument("--asr-workers", type=int, default=3)
    ingest_p.add_argument("--limit", type=int)
    ingest_p.add_argument("--skip-subtitles", action="store_true")

    status_p = sub.add_parser("status", help="Show job status")
    status_p.add_argument("job_id")
    status_p.add_argument("--watch", action="store_true")
    status_p.add_argument("--interval", type=float, default=2.0)
    status_p.add_argument("--gpu-profile")
    status_p.add_argument("--json", action="store_true")

    pull_p = sub.add_parser("pull", help="Pull remote ASR outputs back to local job directory")
    pull_p.add_argument("job_id")
    pull_p.add_argument("--gpu-profile", required=True)

    asr_p = sub.add_parser("run-remote-asr", help="Launch remote GPU ASR for an existing job")
    asr_p.add_argument("job_id")
    asr_p.add_argument("--gpu-profile", required=True)
    asr_p.add_argument("--batch-size", type=int, default=20)
    asr_p.add_argument("--asr-workers", type=int, default=3)
    asr_p.add_argument("--model", default="medium")

    digest_p = sub.add_parser("digest", help="Generate markdown learning docs for a job")
    digest_p.add_argument("job_id")
    digest_p.add_argument("--no-llm", action="store_true")
    digest_p.add_argument("--index", action="store_true", help="Rebuild search index after digest")

    index_p = sub.add_parser("index", help="Build local SQLite search index")
    index_p.add_argument("--docs", default=None)
    index_p.add_argument("--db", default=None)
    index_p.add_argument("--chroma", action="store_true", help="Also build optional Chroma semantic index")
    index_p.add_argument("--chroma-dir", default=None)

    search_p = sub.add_parser("search", help="Search generated markdown digests")
    search_p.add_argument("query")
    search_p.add_argument("--db", default=None)
    search_p.add_argument("-k", "--top-k", type=int, default=8)
    search_p.add_argument("--chroma", action="store_true")
    search_p.add_argument("--chroma-dir", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    store = JobStore(config.jobs_root)

    if args.command == "ingest":
        profile = profile_for_cli(
            config,
            args.gpu_profile,
            args.host,
            args.port,
            args.user,
            args.password_env,
            args.key_filename,
        )
        job_id = ingest(
            args.source,
            config,
            gpu_profile=profile,
            batch_size=args.batch_size,
            asr_workers=args.asr_workers,
            limit=args.limit,
            skip_subtitles=args.skip_subtitles,
        )
        print(job_id)
        print(format_status(store.read_status(job_id)))
        return 0

    if args.command == "status":
        if args.gpu_profile:
            profile = profile_for_cli(config, args.gpu_profile, None, None, None, None, None)
            if args.watch:
                for status in watch_status(profile, args.job_id, store, interval=args.interval):
                    _print_status(status, json_mode=args.json)
                    if not args.json:
                        print()
                return 0
            status = read_remote_status(profile, args.job_id, store)
        else:
            status = store.read_status(args.job_id)
            if args.watch:
                while True:
                    _print_status(status, json_mode=args.json)
                    if status.state in {"done", "failed"}:
                        break
                    time.sleep(args.interval)
                    status = store.read_status(args.job_id)
                    if not args.json:
                        print()
        _print_status(status, json_mode=args.json)
        return 0

    if args.command == "pull":
        profile = profile_for_cli(config, args.gpu_profile, None, None, None, None, None)
        copied = pull_remote_outputs(profile, args.job_id, store)
        print(f"pulled {copied} files")
        return 0

    if args.command == "run-remote-asr":
        from .remote_gpu import deploy_worker

        profile = profile_for_cli(config, args.gpu_profile, None, None, None, None, None)
        videos = [item for item in store.read_videos(args.job_id) if item.needs_asr]
        meta = deploy_worker(
            profile,
            args.job_id,
            videos,
            store,
            batch_size=args.batch_size,
            asr_workers=args.asr_workers,
            model=args.model,
        )
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return 0

    if args.command == "digest":
        job_dir = store.job_dir(args.job_id)
        written = write_digests(job_dir / "transcripts", job_dir / "digests", use_llm=not args.no_llm)
        print(f"wrote {len(written)} digest docs -> {job_dir / 'digests'}")
        if args.index:
            db = config.data_root / "video_learning.sqlite"
            total = build_index(job_dir / "digests", db)
            print(f"indexed {total} chunks -> {db}")
        return 0

    if args.command == "index":
        docs = Path(args.docs) if args.docs else _latest_digest_dir(config.jobs_root)
        db = Path(args.db) if args.db else config.data_root / "video_learning.sqlite"
        total = build_index(docs, db)
        print(f"indexed {total} chunks -> {db}")
        if args.chroma:
            chroma_dir = Path(args.chroma_dir) if args.chroma_dir else config.data_root / "chroma"
            chroma_total = build_chroma_index(docs, chroma_dir)
            print(f"indexed {chroma_total} semantic chunks -> {chroma_dir}")
        return 0

    if args.command == "search":
        if args.chroma:
            chroma_dir = Path(args.chroma_dir) if args.chroma_dir else config.data_root / "chroma"
            for i, item in enumerate(query_chroma(args.query, chroma_dir, top_k=args.top_k), 1):
                meta = item["metadata"]
                print(f"{i}. distance={item['distance']:.3f} | {meta.get('title')} | {meta.get('path')}")
                print(f"   {snippet(item['text'], args.query)}")
                print()
            return 0
        db = Path(args.db) if args.db else config.data_root / "video_learning.sqlite"
        results = search_index(args.query, db, top_k=args.top_k)
        for i, item in enumerate(results, 1):
            print(f"{i}. score={item['score']:.3f} | {item['title']} | {item['video']}")
            print(f"   section: {item['section']}")
            print(f"   path: {item['path']}")
            print(f"   {snippet(item['text'], args.query)}")
            print()
        return 0

    return 2


def _print_status(status, json_mode: bool = False) -> None:
    if json_mode:
        print(json.dumps(status.to_dict(), ensure_ascii=False))
    else:
        print(format_status(status))


def _latest_digest_dir(jobs_root: Path) -> Path:
    candidates = [p / "digests" for p in jobs_root.iterdir() if (p / "digests").exists()] if jobs_root.exists() else []
    if not candidates:
        raise SystemExit("no digest directory found; pass --docs")
    return max(candidates, key=lambda p: p.stat().st_mtime)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (KeyError, RemoteGpuError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
