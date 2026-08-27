from __future__ import annotations

import json
import os
import posixpath
import shlex
import stat
import time
from pathlib import Path

from .config import get_profile_password
from .jobs import JobStore
from .models import GpuProfile, JobStatus, VideoItem


class RemoteGpuError(RuntimeError):
    pass


class RemoteGpuClient:
    def __init__(self, profile: GpuProfile):
        self.profile = profile
        self._client = None

    def __enter__(self) -> "RemoteGpuClient":
        self.connect()
        return self

    def __exit__(self, *_exc) -> None:
        if self._client:
            self._client.close()

    def connect(self) -> None:
        try:
            import paramiko  # type: ignore
        except ModuleNotFoundError as exc:
            raise RemoteGpuError("paramiko is required for SSH. Install with: pip install '.[remote]'") from exc

        password = get_profile_password(self.profile)
        if self.profile.password_env and not password and not self.profile.key_filename:
            raise RemoteGpuError(f"missing SSH password env: {self.profile.password_env}")

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=self.profile.host,
            port=self.profile.port,
            username=self.profile.user,
            password=password,
            key_filename=self.profile.key_filename,
            look_for_keys=not password,
            timeout=20,
        )
        self._client = client

    @property
    def client(self):
        if not self._client:
            raise RemoteGpuError("SSH client is not connected")
        return self._client

    def run(self, command: str, check: bool = True) -> str:
        stdin, stdout, stderr = self.client.exec_command(command)
        del stdin
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        if check and code != 0:
            raise RemoteGpuError(f"remote command failed ({code}): {command}\n{err.strip()}")
        return out

    def sftp(self):
        return self.client.open_sftp()

    def mkdir_p(self, path: str) -> None:
        self.run(f"mkdir -p {shlex.quote(path)}")

    def put(self, local: Path, remote: str) -> None:
        with self.sftp() as sftp:
            self.mkdir_p(posixpath.dirname(remote))
            sftp.put(str(local), remote)

    def get_if_exists(self, remote: str, local: Path) -> bool:
        with self.sftp() as sftp:
            try:
                sftp.stat(remote)
            except OSError:
                return False
            local.parent.mkdir(parents=True, exist_ok=True)
            sftp.get(remote, str(local))
            return True

    def download_tree(self, remote_dir: str, local_dir: Path) -> int:
        local_dir.mkdir(parents=True, exist_ok=True)
        copied = 0
        with self.sftp() as sftp:
            copied += _download_tree_sftp(sftp, remote_dir, local_dir)
        return copied


def _download_tree_sftp(sftp, remote_dir: str, local_dir: Path) -> int:
    copied = 0
    try:
        entries = sftp.listdir_attr(remote_dir)
    except OSError:
        return 0
    for entry in entries:
        remote_path = posixpath.join(remote_dir, entry.filename)
        local_path = local_dir / entry.filename
        if stat.S_ISDIR(entry.st_mode):
            copied += _download_tree_sftp(sftp, remote_path, local_path)
        else:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            sftp.get(remote_path, str(local_path))
            copied += 1
    return copied


def deploy_worker(
    profile: GpuProfile,
    job_id: str,
    videos: list[VideoItem],
    store: JobStore,
    batch_size: int = 20,
    asr_workers: int = 3,
    model: str = "medium",
) -> dict:
    job_dir = store.job_dir(job_id)
    tsv = store.write_tsv(job_id, videos)
    remote_job = posixpath.join(profile.remote_root, "jobs", job_id)
    worker = Path(__file__).parent / "scripts" / "remote_worker.py"

    with RemoteGpuClient(profile) as remote:
        remote.mkdir_p(remote_job)
        remote.put(tsv, posixpath.join(remote_job, "videos.tsv"))
        remote.put(worker, posixpath.join(remote_job, "remote_worker.py"))
        remote.run(
            "python3 -m venv {venv} || true; "
            ". {venv}/bin/activate; "
            "python -m pip install -U pip wheel >/dev/null; "
            "python -m pip install yt-dlp faster-whisper >/dev/null".format(
                venv=shlex.quote(posixpath.join(profile.remote_root, ".venv"))
            ),
            check=True,
        )
        command = (
            f"cd {shlex.quote(remote_job)} && "
            f"nohup {shlex.quote(posixpath.join(profile.remote_root, '.venv/bin/python'))} remote_worker.py "
            f"--input videos.tsv --model {shlex.quote(model)} --batch-size {batch_size} "
            f"--asr-workers {asr_workers} --output-dir outputs --audio-dir audio "
            f"> logs.nohup 2>&1 & echo $!"
        )
        pid = remote.run(command).strip()
    metadata = {
        "remote_job": remote_job,
        "remote_pid": pid,
        "model": model,
        "batch_size": batch_size,
        "asr_workers": asr_workers,
    }
    (job_dir / "remote.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def pull_remote_outputs(profile: GpuProfile, job_id: str, store: JobStore) -> int:
    job_dir = store.job_dir(job_id)
    remote_meta = json.loads((job_dir / "remote.json").read_text(encoding="utf-8"))
    remote_job = remote_meta["remote_job"]
    with RemoteGpuClient(profile) as remote:
        copied = remote.download_tree(posixpath.join(remote_job, "outputs"), job_dir / "transcripts")
        remote.get_if_exists(posixpath.join(remote_job, "status.json"), job_dir / "remote-status.json")
        remote.get_if_exists(posixpath.join(remote_job, "status.jsonl"), job_dir / "logs" / "remote-status.jsonl")
        remote.get_if_exists(posixpath.join(remote_job, "logs.nohup"), job_dir / "logs" / "logs.nohup")
    return copied


def read_remote_status(profile: GpuProfile, job_id: str, store: JobStore) -> JobStatus:
    job_dir = store.job_dir(job_id)
    remote_meta_path = job_dir / "remote.json"
    if not remote_meta_path.exists():
        return store.read_status(job_id)
    remote_meta = json.loads(remote_meta_path.read_text(encoding="utf-8"))
    with RemoteGpuClient(profile) as remote:
        text = remote.run(f"cat {shlex.quote(posixpath.join(remote_meta['remote_job'], 'status.json'))}", check=False)
    if not text.strip():
        return store.read_status(job_id)
    data = json.loads(text)
    status = JobStatus.from_dict(data)
    store.write_status(status)
    return status


def watch_status(profile: GpuProfile, job_id: str, store: JobStore, interval: float = 2.0):
    while True:
        status = read_remote_status(profile, job_id, store)
        yield status
        if status.state in {"done", "failed"}:
            break
        time.sleep(interval)


def redact_env_snapshot() -> dict[str, str]:
    redacted = {}
    for key, value in os.environ.items():
        if "PASSWORD" in key or "TOKEN" in key or "SECRET" in key:
            redacted[key] = "***"
        elif key.startswith("VIDEO_GPU_"):
            redacted[key] = "***"
    return redacted

