from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional


class TodoStatus(str, Enum):
    ACTIVE = "active"
    DONE = "done"


class TodoStoreLimitError(Exception):
    """Raised when the store cannot accept more active todos."""


def new_uid() -> str:
    return str(uuid.uuid4())


DEFAULT_BUCKETS = ["work", "personal"]
DEFAULT_BUCKET = "personal"
WORK_BUCKET = "work"
PERSONAL_BUCKET = "personal"


def normalize_bucket(name: str) -> str:
    name = name.strip().lower().replace(" ", "-").replace("_", "-")
    if name in ("inbox", "priority"):
        return DEFAULT_BUCKET
    return name


BUCKET_STYLES: dict[str, str] = {
    "work": "blue",
    "personal": "green",
}


def bucket_style(bucket: str) -> str:
    return BUCKET_STYLES.get(bucket, "cyan")


@dataclass
class Todo:
    id: int
    title: str
    uid: str = field(default_factory=new_uid)
    bucket: str = DEFAULT_BUCKET
    done: bool = False
    parent_id: Optional[int] = None
    parent_uid: Optional[str] = None
    due_date: Optional[date] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    def touch(self) -> None:
        self.updated_at = datetime.now()

    @property
    def status(self) -> TodoStatus:
        return TodoStatus.DONE if self.done else TodoStatus.ACTIVE

    def is_overdue(self, today: Optional[date] = None) -> bool:
        if self.done or self.due_date is None:
            return False
        today = today or date.today()
        return self.due_date < today

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "uid": self.uid,
            "title": self.title,
            "bucket": self.bucket,
            "done": self.done,
            "parent_id": self.parent_id,
            "parent_uid": self.parent_uid,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Todo:
        created_at = datetime.fromisoformat(data["created_at"])
        return cls(
            id=data["id"],
            title=data["title"],
            uid=data.get("uid") or new_uid(),
            bucket=normalize_bucket(data.get("bucket") or DEFAULT_BUCKET),
            done=data["done"],
            parent_id=data.get("parent_id"),
            parent_uid=data.get("parent_uid") or None,
            due_date=date.fromisoformat(data["due_date"]) if data.get("due_date") else None,
            created_at=created_at,
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else created_at,
            completed_at=(
                datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None
            ),
        )


@dataclass
class MergeReport:
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0

    @property
    def changed(self) -> bool:
        return self.added > 0 or self.updated > 0 or self.removed > 0


@dataclass
class TodoStore:
    todos: list[Todo] = field(default_factory=list)
    next_id: int = 1
    deletions: dict[str, datetime] = field(default_factory=dict)
    buckets: list[str] = field(default_factory=lambda: list(DEFAULT_BUCKETS))

    def ensure_bucket(self, bucket: str) -> str:
        bucket = normalize_bucket(bucket)
        if bucket not in self.buckets:
            self.buckets.append(bucket)
        return bucket

    def bucket_order(self) -> list[str]:
        preferred = [b for b in DEFAULT_BUCKETS if b in self.buckets]
        custom = sorted(b for b in self.buckets if b not in DEFAULT_BUCKETS)
        return preferred + custom

    def get(self, todo_id: int) -> Optional[Todo]:
        return next((t for t in self.todos if t.id == todo_id), None)

    def get_by_uid(self, uid: str) -> Optional[Todo]:
        return next((t for t in self.todos if t.uid == uid), None)

    def children_of(self, parent_id: int) -> list[Todo]:
        return [t for t in self.todos if t.parent_id == parent_id]

    def descendants_of(self, parent_id: int) -> list[Todo]:
        result: list[Todo] = []
        for child in self.children_of(parent_id):
            result.append(child)
            result.extend(self.descendants_of(child.id))
        return result

    def root_todos(self) -> list[Todo]:
        return [t for t in self.todos if t.parent_id is None]

    def active_count(self) -> int:
        return sum(1 for t in self.todos if not t.done)

    def _completed_sort_key(self, todo: Todo) -> datetime:
        return todo.completed_at or todo.updated_at or todo.created_at

    def cleanup_completed(self, max_todos: int) -> int:
        """Remove oldest completed todos until the store is at or below max_todos."""
        removed = 0
        while len(self.todos) > max_todos:
            completed = [t for t in self.todos if t.done]
            if not completed:
                break
            oldest = min(completed, key=self._completed_sort_key)
            self.remove(oldest.id)
            removed += 1
        return removed

    def normalize(self) -> None:
        """Fill sync metadata on legacy todos and keep parent_uid in sync."""
        for todo in self.todos:
            if not todo.uid:
                todo.uid = new_uid()
            if todo.updated_at is None:
                todo.updated_at = todo.created_at
            todo.bucket = normalize_bucket(todo.bucket or DEFAULT_BUCKET)
            self.ensure_bucket(todo.bucket)

        if not self.buckets:
            self.buckets = list(DEFAULT_BUCKETS)
        seen: set[str] = set()
        unique: list[str] = []
        for bucket in self.buckets:
            if bucket not in seen:
                seen.add(bucket)
                unique.append(bucket)
        self.buckets = unique
        for bucket in DEFAULT_BUCKETS:
            if bucket not in self.buckets:
                self.buckets.append(bucket)

        for todo in self.todos:
            if todo.parent_id is not None:
                parent = self.get(todo.parent_id)
                if parent:
                    todo.parent_uid = parent.uid

        if self.todos and self.next_id <= max(t.id for t in self.todos):
            self.next_id = max(t.id for t in self.todos) + 1

    def add(
        self,
        title: str,
        parent_id: Optional[int] = None,
        due_date: Optional[date] = None,
        bucket: Optional[str] = None,
    ) -> Todo:
        parent_uid = None
        resolved_bucket = normalize_bucket(bucket) if bucket else DEFAULT_BUCKET
        if parent_id is not None:
            parent = self.get(parent_id)
            if parent:
                parent_uid = parent.uid
                if bucket is None:
                    resolved_bucket = parent.bucket

        resolved_bucket = self.ensure_bucket(resolved_bucket)

        todo = Todo(
            id=self.next_id,
            title=title,
            bucket=resolved_bucket,
            parent_id=parent_id,
            parent_uid=parent_uid,
            due_date=due_date,
        )
        self.todos.append(todo)
        self.next_id += 1
        return todo

    def move_to_bucket(self, todo_id: int, bucket: str, cascade: bool = True) -> Todo:
        todo = self.get(todo_id)
        if todo is None:
            raise KeyError(todo_id)
        resolved = self.ensure_bucket(bucket)
        todo.bucket = resolved
        todo.touch()
        if cascade:
            for desc in self.descendants_of(todo_id):
                desc.bucket = resolved
                desc.touch()
        return todo

    def remove(self, todo_id: int) -> list[Todo]:
        """Remove a todo and all its descendants. Returns removed todos."""
        to_remove = {todo_id}
        for desc in self.descendants_of(todo_id):
            to_remove.add(desc.id)

        removed = [t for t in self.todos if t.id in to_remove]
        now = datetime.now()
        for todo in removed:
            self.deletions[todo.uid] = now

        self.todos = [t for t in self.todos if t.id not in to_remove]
        return removed

    def mark_done(self, todo_id: int, recursive: bool = True) -> Todo:
        todo = self.get(todo_id)
        if todo is None:
            raise KeyError(todo_id)
        if not todo.done:
            todo.completed_at = datetime.now()
        todo.done = True
        todo.touch()
        if recursive:
            for child in self.descendants_of(todo_id):
                if not child.done:
                    child.completed_at = datetime.now()
                child.done = True
                child.touch()
        return todo

    def reopen(self, todo_id: int) -> Todo:
        todo = self.get(todo_id)
        if todo is None:
            raise KeyError(todo_id)
        todo.done = False
        todo.completed_at = None
        todo.touch()
        # Reopen any done ancestors so the tree stays consistent.
        parent_id = todo.parent_id
        while parent_id is not None:
            parent = self.get(parent_id)
            if parent is None or not parent.done:
                break
            parent.done = False
            parent.completed_at = None
            parent.touch()
            parent_id = parent.parent_id
        return todo

    def to_dict(self) -> dict:
        return {
            "todos": [t.to_dict() for t in self.todos],
            "next_id": self.next_id,
            "buckets": self.buckets,
            "deletions": {uid: ts.isoformat() for uid, ts in self.deletions.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> TodoStore:
        store = cls()
        store.todos = [Todo.from_dict(t) for t in data.get("todos", [])]
        store.next_id = data.get("next_id", 1)
        seen: set[str] = set()
        normalized_buckets: list[str] = []
        for b in data.get("buckets", list(DEFAULT_BUCKETS)):
            nb = normalize_bucket(b)
            if nb not in seen:
                seen.add(nb)
                normalized_buckets.append(nb)
        store.buckets = normalized_buckets
        store.deletions = {
            uid: datetime.fromisoformat(ts)
            for uid, ts in data.get("deletions", {}).items()
        }
        store.normalize()
        return store


def _todo_content_key(todo: Todo) -> tuple:
    return (
        todo.title,
        todo.bucket,
        todo.done,
        todo.parent_uid,
        todo.due_date,
        todo.completed_at,
    )


def merge_stores(local: TodoStore, remote: TodoStore) -> tuple[TodoStore, MergeReport]:
    """Merge two stores, preferring the most recently updated version of each todo."""
    local.normalize()
    remote.normalize()
    report = MergeReport()

    merged_deletions: dict[str, datetime] = {}
    for uid in set(local.deletions) | set(remote.deletions):
        local_ts = local.deletions.get(uid)
        remote_ts = remote.deletions.get(uid)
        if local_ts and remote_ts:
            merged_deletions[uid] = max(local_ts, remote_ts)
        else:
            merged_deletions[uid] = local_ts or remote_ts  # type: ignore[assignment]

    local_by_uid = {t.uid: t for t in local.todos}
    remote_by_uid = {t.uid: t for t in remote.todos}
    chosen: dict[str, Todo] = {}

    for uid in set(local_by_uid) | set(remote_by_uid):
        deleted_at = merged_deletions.get(uid)
        local_todo = local_by_uid.get(uid)
        remote_todo = remote_by_uid.get(uid)

        if local_todo and remote_todo:
            if deleted_at and deleted_at >= max(local_todo.updated_at, remote_todo.updated_at):
                report.removed += 1
                continue
            if local_todo.updated_at >= remote_todo.updated_at:
                winner = local_todo
                if _todo_content_key(local_todo) != _todo_content_key(remote_todo):
                    report.updated += 1
                else:
                    report.unchanged += 1
            else:
                winner = remote_todo
                if _todo_content_key(remote_todo) != _todo_content_key(local_todo):
                    report.updated += 1
                else:
                    report.unchanged += 1
            chosen[uid] = winner
        elif local_todo:
            if deleted_at and deleted_at >= local_todo.updated_at:
                report.removed += 1
                continue
            chosen[uid] = local_todo
            report.added += 1
        elif remote_todo:
            if deleted_at and deleted_at >= remote_todo.updated_at:
                report.removed += 1
                continue
            chosen[uid] = remote_todo
            report.added += 1

    result = TodoStore()
    result.deletions = merged_deletions
    result.buckets = sorted(
        set(local.buckets) | set(remote.buckets),
        key=lambda b: (
            local.bucket_order().index(b)
            if b in local.bucket_order()
            else len(DEFAULT_BUCKETS) + ord(b[0])
        ),
    )
    for bucket in DEFAULT_BUCKETS:
        result.ensure_bucket(bucket)
    uid_to_id: dict[str, int] = {}

    sorted_todos = sorted(chosen.values(), key=lambda t: (t.created_at, t.uid))
    for todo in sorted_todos:
        uid_to_id[todo.uid] = result.next_id
        result.next_id += 1

    for todo in sorted_todos:
        parent_id = None
        if todo.parent_uid and todo.parent_uid in uid_to_id:
            parent_id = uid_to_id[todo.parent_uid]

        result.todos.append(
            Todo(
                id=uid_to_id[todo.uid],
                uid=todo.uid,
                title=todo.title,
                bucket=todo.bucket,
                done=todo.done,
                parent_id=parent_id,
                parent_uid=todo.parent_uid if parent_id else None,
                due_date=todo.due_date,
                created_at=todo.created_at,
                updated_at=todo.updated_at,
                completed_at=todo.completed_at,
            )
        )

    result.normalize()
    return result, report
