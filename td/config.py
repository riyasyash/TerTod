from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / ".td"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"
DEFAULT_SYNC_DIR = DEFAULT_CONFIG_DIR / "repo"
DEFAULT_MAX_TODOS = 1000


@dataclass
class SyncConfig:
    remote: str
    branch: str = "main"
    file: str = "todos.json"
    dir: Path = DEFAULT_SYNC_DIR
    last_synced_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "remote": self.remote,
            "branch": self.branch,
            "file": self.file,
            "dir": str(self.dir),
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SyncConfig:
        last_synced = data.get("last_synced_at")
        return cls(
            remote=data["remote"],
            branch=data.get("branch", "main"),
            file=data.get("file", "todos.json"),
            dir=Path(data.get("dir", DEFAULT_SYNC_DIR)),
            last_synced_at=datetime.fromisoformat(last_synced) if last_synced else None,
        )


@dataclass
class AppConfig:
    sync: SyncConfig | None = None
    show_personal: bool = False
    max_todos: int = DEFAULT_MAX_TODOS

    def to_dict(self) -> dict:
        data: dict = {
            "show_personal": self.show_personal,
            "max_todos": self.max_todos,
        }
        if self.sync:
            data["sync"] = self.sync.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> AppConfig:
        sync_data = data.get("sync")
        return cls(
            sync=SyncConfig.from_dict(sync_data) if sync_data else None,
            show_personal=bool(data.get("show_personal", False)),
            max_todos=int(data.get("max_todos", DEFAULT_MAX_TODOS)),
        )


def get_config_path() -> Path:
    return Path(os.environ.get("TD_CONFIG", DEFAULT_CONFIG_FILE))


def load_config(path: Path | None = None) -> AppConfig:
    path = path or get_config_path()
    if not path.exists():
        return AppConfig()
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return AppConfig.from_dict(data)


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    path = path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path
