from __future__ import annotations

from datetime import date
from typing import Optional

from td.config import AppConfig, DEFAULT_MAX_TODOS, load_config
from td.models import Todo, TodoStore, TodoStoreLimitError


def get_max_todos(config: AppConfig | None = None) -> int:
    config = config or load_config()
    return config.max_todos


def enforce_todo_limits(store: TodoStore, max_todos: int | None = None) -> int:
    """Drop oldest completed todos when over the limit. Returns removed count."""
    limit = max_todos if max_todos is not None else get_max_todos()
    return store.cleanup_completed(limit)


def add_with_limit(
    store: TodoStore,
    title: str,
    parent_id: Optional[int] = None,
    due_date: Optional[date] = None,
    bucket: Optional[str] = None,
    max_todos: int | None = None,
) -> Todo:
    limit = max_todos if max_todos is not None else get_max_todos()
    active = store.active_count()
    if active >= limit:
        raise TodoStoreLimitError(
            f"Cannot add todo: {active} active todos (limit: {limit}). "
            "Complete or remove todos first."
        )
    todo = store.add(title, parent_id=parent_id, due_date=due_date, bucket=bucket)
    enforce_todo_limits(store, limit)
    return todo
