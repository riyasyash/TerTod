from __future__ import annotations

import json
import os
from pathlib import Path

from td.limits import enforce_todo_limits
from td.models import TodoStore

DEFAULT_DATA_DIR = Path.home() / ".td"
DEFAULT_DATA_FILE = DEFAULT_DATA_DIR / "todos.json"


def get_data_path() -> Path:
    return Path(os.environ.get("TD_DATA", DEFAULT_DATA_FILE))


def ensure_data_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_store(path: Path | None = None) -> TodoStore:
    path = path or get_data_path()
    if not path.exists():
        return TodoStore()
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    store = TodoStore.from_dict(data)
    store.normalize()
    enforce_todo_limits(store)
    return store


def save_store(store: TodoStore, path: Path | None = None) -> Path:
    path = path or get_data_path()
    enforce_todo_limits(store)
    ensure_data_dir(path)
    with path.open("w", encoding="utf-8") as f:
        json.dump(store.to_dict(), f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path
