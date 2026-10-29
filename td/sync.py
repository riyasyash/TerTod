from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from td.config import AppConfig, SyncConfig, load_config, save_config
from td.limits import enforce_todo_limits
from td.models import MergeReport, TodoStore, merge_stores
from td.storage import get_data_path, load_store, save_store


class SyncError(Exception):
    pass


@dataclass
class SyncResult:
    report: MergeReport
    pushed: bool
    message: str


def _run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SyncError("git is not installed or not on PATH.") from exc

    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise SyncError(f"git {' '.join(args)} failed: {detail}")
    return result


def _ensure_repo(sync: SyncConfig) -> Path:
    repo_dir = sync.dir
    if (repo_dir / ".git").exists():
        _run_git(["fetch", "origin"], repo_dir)
        pull = _run_git(["pull", "--rebase", "origin", sync.branch], repo_dir, check=False)
        if pull.returncode != 0:
            detail = (pull.stderr or pull.stdout or "").strip()
            raise SyncError(f"Could not pull latest changes: {detail}")
        return repo_dir

    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    if repo_dir.exists() and any(repo_dir.iterdir()):
        raise SyncError(
            f"Sync directory {repo_dir} exists but is not a git repo. "
            "Remove it or choose another path with --dir."
        )

    clone = _run_git(["clone", sync.remote, str(repo_dir)], Path.cwd(), check=False)
    if clone.returncode != 0:
        detail = (clone.stderr or clone.stdout or "").strip()
        raise SyncError(f"Could not clone remote: {detail}")

    return repo_dir


def _repo_file(sync: SyncConfig) -> Path:
    return sync.dir / sync.file


def _has_uncommitted_changes(repo_dir: Path, filename: str) -> bool:
    result = _run_git(["status", "--porcelain", filename], repo_dir, check=False)
    return bool(result.stdout.strip())


def _commit_and_push(sync: SyncConfig, message: str) -> bool:
    repo_dir = sync.dir
    filename = sync.file

    if not _has_uncommitted_changes(repo_dir, filename):
        return False

    _run_git(["add", filename], repo_dir)
    _run_git(["commit", "-m", message], repo_dir)
    push = _run_git(["push", "origin", sync.branch], repo_dir, check=False)
    if push.returncode != 0:
        detail = (push.stderr or push.stdout or "").strip()
        raise SyncError(f"Push failed: {detail}")
    return True


def sync_todos(message: str = "chore: sync todos", dry_run: bool = False) -> SyncResult:
    config = load_config()
    if config.sync is None:
        raise SyncError(
            "No git remote configured. Run: td remote set <git-url>"
        )

    sync = config.sync
    local_path = get_data_path()
    local_store = load_store(local_path)

    repo_dir = _ensure_repo(sync)
    remote_path = _repo_file(sync)

    if remote_path.exists():
        remote_store = load_store(remote_path)
    else:
        remote_store = TodoStore()

    merged, report = merge_stores(local_store, remote_store)
    enforce_todo_limits(merged)

    if dry_run:
        if report.changed:
            msg = (
                f"Dry run: would merge {report.added} new, "
                f"{report.updated} updated, {report.removed} removed."
            )
        else:
            msg = "Dry run: local and remote are already in sync."
        return SyncResult(report=report, pushed=False, message=msg)

    save_store(merged, local_path)
    save_store(merged, remote_path)

    pushed = False
    if report.changed or _has_uncommitted_changes(repo_dir, sync.file):
        pushed = _commit_and_push(sync, message)

    sync.last_synced_at = datetime.now()
    config.sync = sync
    save_config(config)

    if report.changed:
        msg = (
            f"Synced {report.added} new, {report.updated} updated, "
            f"{report.removed} removed."
        )
    else:
        msg = "Already in sync."

    if pushed:
        msg += " Pushed to remote."
    elif report.changed:
        msg += " Saved locally and in repo."

    return SyncResult(report=report, pushed=pushed, message=msg)


def sync_status() -> dict:
    config = load_config()
    local_store = load_store()
    info: dict = {
        "configured": config.sync is not None,
        "local_path": str(get_data_path()),
        "local_count": len(local_store.todos),
    }

    if config.sync is None:
        return info

    sync = config.sync
    info.update(
        {
            "remote": sync.remote,
            "branch": sync.branch,
            "repo_file": sync.file,
            "repo_dir": str(sync.dir),
            "last_synced_at": (
                sync.last_synced_at.isoformat() if sync.last_synced_at else None
            ),
        }
    )

    remote_path = _repo_file(sync)
    if remote_path.exists():
        remote_store = load_store(remote_path)
        info["remote_count"] = len(remote_store.todos)
        _, report = merge_stores(local_store, remote_store)
        info["pending_adds"] = report.added
        info["pending_updates"] = report.updated
        info["pending_removals"] = report.removed
        info["in_sync"] = not report.changed
    else:
        info["remote_count"] = 0
        info["in_sync"] = len(local_store.todos) == 0
        info["pending_adds"] = len(local_store.todos)

    return info
