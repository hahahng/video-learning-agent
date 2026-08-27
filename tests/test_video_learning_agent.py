from __future__ import annotations

import json
from pathlib import Path

from video_learning_agent.config import load_config
from video_learning_agent.digest import fallback_digest, validate_digest
from video_learning_agent.jobs import JobStatus, format_status
from video_learning_agent.resolver import platform_for_url, read_tsv
from video_learning_agent.search import build_index, search_index
from video_learning_agent.subtitles import normalize_caption


def test_platform_detection():
    assert platform_for_url("https://www.bilibili.com/video/BV1xx") == "bilibili"
    assert platform_for_url("https://youtu.be/abc") == "youtube"
    assert platform_for_url("https://example.com") == "unknown"


def test_read_tsv(tmp_path: Path):
    path = tmp_path / "videos.tsv"
    path.write_text("index\tbv\ttitle\turl\tduration\n1\tBVabc\t标题\thttps://www.bilibili.com/video/BVabc\t12\n", encoding="utf-8")
    items = read_tsv(path)
    assert len(items) == 1
    assert items[0].video_id == "BVabc"
    assert items[0].platform == "bilibili"


def test_json3_caption_normalization(tmp_path: Path):
    path = tmp_path / "a.zh.json3"
    path.write_text(
        json.dumps(
            {
                "events": [
                    {"tStartMs": 1000, "segs": [{"utf8": "你好"}, {"utf8": "世界"}]},
                    {"tStartMs": 2000, "segs": [{"utf8": "第二句"}]},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    from video_learning_agent.models import VideoItem

    text = normalize_caption(path, VideoItem(1, "BVabc", "标题", "https://www.bilibili.com/video/BVabc"))
    assert "# 标题" in text
    assert "[00:00:01] 你好世界" in text
    assert "- Source: subtitle" in text


def test_status_format():
    status = JobStatus(job_id="j", state="ASR 中", total=73, audio_done=51, transcript_done=18, current="BVxxx")
    text = format_status(status)
    assert "进度：ASR 中" in text
    assert "音频：51 / 73" in text
    assert "错误：无" in text


def test_fallback_digest_has_required_sections():
    text = fallback_digest("测试标题", "这是一个知识点。老师讲了一个具体例子。可以使用 python script 完成自动化。", 2)
    assert validate_digest(text)
    assert "# 02｜测试标题" in text


def test_search_index(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "01.md").write_text(
        "# 01｜二维码传文件\n\n## 1. 知识点\n\n屏幕光传文件可以用二维码分片和纠错。\n",
        encoding="utf-8",
    )
    db = tmp_path / "index.sqlite"
    assert build_index(docs, db) > 0
    results = search_index("二维码", db)
    assert results
    assert "二维码" in results[0]["text"]


def test_config_does_not_store_password(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "video-agent.config.yaml"
    cfg.write_text(
        """
gpu_profiles:
  seeta:
    host: connect.example.com
    port: 22293
    user: root
    password_env: VIDEO_GPU_PASSWORD
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("VIDEO_GPU_PASSWORD", "secret")
    config = load_config(cfg)
    profile = config.gpu_profiles["seeta"]
    assert profile.password_env == "VIDEO_GPU_PASSWORD"
    assert "secret" not in repr(profile)

