from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .models import AgentConfig, GpuProfile


DEFAULT_CONFIG_PATHS = (
    Path("video-agent.config.yaml"),
    Path("video-agent.config.yml"),
    Path("video-agent.config.json"),
)


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value.isdigit():
        return int(value)
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return value.strip("\"'")


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """Parse the small YAML subset used by GPU profile config."""
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        key, sep, value = line.strip().partition(":")
        if not sep:
            continue
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value.strip():
            parent[key] = _parse_scalar(value)
        else:
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
    return root


def read_config_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        return data or {}
    except ModuleNotFoundError:
        return _parse_simple_yaml(text)


def load_config(path: str | Path | None = None) -> AgentConfig:
    config_path = Path(path) if path else next((p for p in DEFAULT_CONFIG_PATHS if p.exists()), None)
    data: dict[str, Any] = read_config_file(config_path) if config_path else {}

    jobs_root = Path(data.get("jobs_root") or "work/jobs")
    data_root = Path(data.get("data_root") or "data")
    profiles: dict[str, GpuProfile] = {}
    for name, profile in (data.get("gpu_profiles") or {}).items():
        profiles[name] = GpuProfile(
            name=name,
            host=str(profile["host"]),
            port=int(profile["port"]),
            user=str(profile.get("user") or "root"),
            remote_root=str(profile.get("remote_root") or "/root/autodl-tmp/video-learning-agent"),
            password_env=profile.get("password_env"),
            key_filename=profile.get("key_filename"),
        )
    return AgentConfig(jobs_root=jobs_root, data_root=data_root, gpu_profiles=profiles)


def get_profile_password(profile: GpuProfile) -> str | None:
    if not profile.password_env:
        return None
    return os.environ.get(profile.password_env)


def profile_for_cli(
    config: AgentConfig,
    name: str | None,
    host: str | None,
    port: int | None,
    user: str | None,
    password_env: str | None,
    key_filename: str | None,
) -> GpuProfile | None:
    if name:
        if name not in config.gpu_profiles:
            raise KeyError(f"GPU profile not found: {name}")
        return config.gpu_profiles[name]
    if host and port:
        return GpuProfile(
            name="cli",
            host=host,
            port=port,
            user=user or "root",
            password_env=password_env,
            key_filename=key_filename,
        )
    return None

