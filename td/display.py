from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from td.models import (
    DEFAULT_BUCKETS,
    PERSONAL_BUCKET,
    Todo,
    TodoStore,
    bucket_style,
    normalize_bucket,
)

console = Console()


class ListFilter(str, Enum):
    ALL = "all"
    ACTIVE = "active"
    DONE = "done"
    OVERDUE = "overdue"
    TODAY = "today"


def _status_icon(todo: Todo, today: date) -> str:
    if todo.done:
        return "✓"
    if todo.is_overdue(today):
        return "!"
    if todo.due_date == today:
        return "◉"
    return "○"


def _format_due(todo: Todo, today: date) -> Text:
    if todo.due_date is None:
        return Text("—", style="dim")

    label = todo.due_date.strftime("%b %d, %Y")
    if todo.done:
        return Text(label, style="dim strikethrough")
    if todo.is_overdue(today):
        return Text(label, style="bold red")
    if todo.due_date == today:
        return Text(f"{label} (today)", style="bold yellow")
    return Text(label, style="cyan")


def _format_title(todo: Todo, today: date) -> Text:
    text = Text(todo.title)
    if todo.done:
        text.stylize("dim strikethrough")
    elif todo.is_overdue(today):
        text.stylize("bold red")
    return text


def _format_bucket(bucket: str) -> Text:
    return Text(bucket, style=bucket_style(bucket))


def _personal_hidden(bucket_filter: Optional[str], show_personal: bool) -> bool:
    return not show_personal and bucket_filter != PERSONAL_BUCKET


def _sort_done_items(items: list[tuple[Todo, int]]) -> list[tuple[Todo, int]]:
    return sorted(
        items,
        key=lambda pair: pair[0].completed_at or pair[0].updated_at,
        reverse=True,
    )


def _build_todo_tree(
    store: TodoStore,
    parent_id: Optional[int],
    today: date,
    filter_mode: ListFilter,
    bucket_filter: Optional[str] = None,
    show_personal: bool = False,
) -> list[tuple[Todo, int]]:
    """Return (todo, depth) pairs in tree order."""
    items: list[tuple[Todo, int]] = []
    hide_personal = _personal_hidden(bucket_filter, show_personal)

    def walk(pid: Optional[int], depth: int) -> None:
        children = (
            store.children_of(pid) if pid is not None else store.root_todos()
        )
        children.sort(key=lambda t: (t.done, t.id))

        for todo in children:
            if bucket_filter and todo.bucket != bucket_filter:
                walk(todo.id, depth + 1)
                continue
            if hide_personal and todo.bucket == PERSONAL_BUCKET:
                walk(todo.id, depth + 1)
                continue
            if _matches_filter(todo, today, filter_mode):
                items.append((todo, depth))
            elif filter_mode == ListFilter.ALL:
                items.append((todo, depth))
            walk(todo.id, depth + 1)

    walk(parent_id, 0)
    if filter_mode == ListFilter.DONE:
        return _sort_done_items(items)
    return items


def _bucket_sort_key(store: TodoStore, bucket: str) -> tuple:
    order = store.bucket_order()
    if bucket in order:
        return (order.index(bucket), bucket)
    return (len(order), bucket)


def collect_visible_todos(
    store: TodoStore,
    filter_mode: ListFilter = ListFilter.ACTIVE,
    bucket_filter: Optional[str] = None,
    show_personal: bool = False,
) -> list[tuple[Todo, int]]:
    today = date.today()
    normalized = normalize_bucket(bucket_filter) if bucket_filter else None
    return _build_todo_tree(store, None, today, filter_mode, normalized, show_personal)


def visible_todos(
    store: TodoStore,
    filter_mode: ListFilter = ListFilter.ACTIVE,
    bucket_filter: Optional[str] = None,
    show_personal: bool = False,
) -> list[Todo]:
    return [todo for todo, _ in collect_visible_todos(store, filter_mode, bucket_filter, show_personal)]


def status_icon(todo: Todo, today: Optional[date] = None) -> str:
    return _status_icon(todo, today or date.today())


def due_label(todo: Todo, today: Optional[date] = None) -> str:
    today = today or date.today()
    if todo.due_date is None:
        return "—"
    label = todo.due_date.strftime("%b %d")
    if todo.is_overdue(today):
        return f"!{label}"
    if todo.due_date == today:
        return f"*{label}"
    return label


def completed_label(todo: Todo) -> str:
    if todo.completed_at:
        return todo.completed_at.strftime("%b %d, %Y %H:%M")
    return "—"


def _format_completed(todo: Todo) -> Text:
    if todo.completed_at:
        return Text(todo.completed_at.strftime("%b %d, %Y %H:%M"), style="dim")
    return Text("—", style="dim")


def _matches_filter(todo: Todo, today: date, filter_mode: ListFilter) -> bool:
    if filter_mode == ListFilter.ALL:
        return True
    if filter_mode == ListFilter.ACTIVE:
        return not todo.done
    if filter_mode == ListFilter.DONE:
        return todo.done
    if filter_mode == ListFilter.OVERDUE:
        return todo.is_overdue(today)
    if filter_mode == ListFilter.TODAY:
        return todo.due_date == today and not todo.done
    return True


def _render_todo_table(
    store: TodoStore,
    items: list[tuple[Todo, int]],
    today: date,
    show_bucket: bool = True,
    show_completed: bool = False,
) -> Table:
    table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold magenta",
        padding=(0, 1),
        expand=True,
    )
    table.add_column("", width=3, justify="center")
    table.add_column("ID", style="dim", width=5, justify="right")
    table.add_column("Task", ratio=3)
    if show_bucket:
        table.add_column("Bucket", width=12)
    if show_completed:
        table.add_column("Completed", width=18)
    else:
        table.add_column("Due", width=18)
    if not show_completed:
        table.add_column("Status", width=10)

    for todo, depth in items:
        indent = "  " * depth + ("└ " if depth else "")
        icon = _status_icon(todo, today)
        icon_style = (
            "bold green" if todo.done
            else "bold red" if todo.is_overdue(today)
            else "bold yellow" if todo.due_date == today
            else "cyan"
        )

        title = _format_title(todo, today)
        title = Text(indent) + title

        row = [
            Text(icon, style=icon_style),
            str(todo.id),
            title,
        ]
        if show_bucket:
            row.append(_format_bucket(todo.bucket))
        if show_completed:
            row.append(_format_completed(todo))
        else:
            status = Text("done" if todo.done else "active")
            status.stylize("green" if todo.done else "yellow")
            row.extend([_format_due(todo, today), status])
        table.add_row(*row)

    return table


def render_todo_list(
    store: TodoStore,
    filter_mode: ListFilter = ListFilter.ALL,
    bucket_filter: Optional[str] = None,
    show_personal: bool = False,
) -> None:
    today = date.today()
    bucket_filter = normalize_bucket(bucket_filter) if bucket_filter else None
    items = _build_todo_tree(store, None, today, filter_mode, bucket_filter, show_personal)
    show_completed = filter_mode == ListFilter.DONE

    if not items:
        bucket_note = f" in [bold]{bucket_filter}[/bold]" if bucket_filter else ""
        personal_note = (
            " (personal hidden — use [bold]--show-personal[/bold] or [b]p[/b] in TUI)"
            if _personal_hidden(bucket_filter, show_personal)
            else ""
        )
        messages = {
            ListFilter.ALL: f"No todos{bucket_note} yet{personal_note}. Add one with [bold]td add \"your task\"[/bold]",
            ListFilter.ACTIVE: f"No active todos{bucket_note}{personal_note} — you're all caught up!",
            ListFilter.DONE: f"No completed todos{bucket_note} yet.",
            ListFilter.OVERDUE: f"No overdue todos{bucket_note} — nice work!",
            ListFilter.TODAY: f"Nothing due today{bucket_note}.",
        }
        console.print(Panel(messages[filter_mode], border_style="dim", title="td"))
        return

    filter_labels = {
        ListFilter.ALL: "All Todos",
        ListFilter.ACTIVE: "Active Todos",
        ListFilter.DONE: "Completed Todos",
        ListFilter.OVERDUE: "Overdue Todos",
        ListFilter.TODAY: "Due Today",
    }
    title_suffix = filter_labels[filter_mode]
    if bucket_filter:
        title_suffix += f" · {bucket_filter}"

    if bucket_filter or show_completed:
        table = _render_todo_table(
            store, items, today, show_bucket=not bucket_filter, show_completed=show_completed
        )
        console.print(
            Panel(table, title=f"[bold]td[/bold] — {title_suffix}", border_style="blue")
        )
        return

    by_bucket: dict[str, list[tuple[Todo, int]]] = {}
    for item in items:
        by_bucket.setdefault(item[0].bucket, []).append(item)

    sorted_buckets = sorted(by_bucket.keys(), key=lambda b: _bucket_sort_key(store, b))
    for bucket in sorted_buckets:
        bucket_items = by_bucket[bucket]
        table = _render_todo_table(store, bucket_items, today, show_bucket=False)
        style = bucket_style(bucket)
        console.print(
            Panel(
                table,
                title=f"[{style}]{bucket}[/] · {len(bucket_items)} item(s)",
                border_style=style.split()[-1] if style.split() else "blue",
            )
        )


def render_bucket_list(store: TodoStore, show_personal: bool = False) -> None:
    table = Table(box=box.SIMPLE_HEAD, header_style="bold magenta", padding=(0, 1))
    table.add_column("Bucket", ratio=2)
    table.add_column("Active", justify="right", width=8)
    table.add_column("Done", justify="right", width=8)
    table.add_column("Total", justify="right", width=8)

    for bucket in store.bucket_order():
        todos = [t for t in store.todos if t.bucket == bucket]
        if not todos and bucket not in DEFAULT_BUCKETS:
            continue
        active = sum(1 for t in todos if not t.done)
        done = sum(1 for t in todos if t.done)
        label = bucket
        if bucket == PERSONAL_BUCKET and _personal_hidden(None, show_personal):
            label = f"{bucket} (hidden)"
        table.add_row(
            Text(label, style=bucket_style(bucket)),
            str(active),
            str(done),
            str(len(todos)),
        )

    console.print(Panel(table, title="Buckets", border_style="blue"))


def render_todo_detail(store: TodoStore, todo: Todo) -> None:
    today = date.today()
    tree = Tree(f"[bold]#{todo.id}[/bold] {_format_title(todo, today)}")

    def add_children(parent_node: Tree, parent_id: int) -> None:
        for child in sorted(store.children_of(parent_id), key=lambda t: t.id):
            icon = _status_icon(child, today)
            label = f"[{icon}] #{child.id} {child.title}"
            if child.done:
                label = f"[dim strike]{label}[/dim strike]"
            node = parent_node.add(label)
            add_children(node, child.id)

    add_children(tree, todo.id)

    info_lines = [
        f"[bold]Bucket:[/bold]  {_format_bucket(todo.bucket).plain}",
        f"[bold]Status:[/bold]   {'done' if todo.done else 'active'}",
        f"[bold]Due:[/bold]      {_format_due(todo, today).plain or '—'}",
        f"[bold]Created:[/bold]  {todo.created_at.strftime('%b %d, %Y %H:%M')}",
    ]
    if todo.completed_at:
        info_lines.append(
            f"[bold]Completed:[/bold] {todo.completed_at.strftime('%b %d, %Y %H:%M')}"
        )
    if todo.parent_id is not None:
        parent = store.get(todo.parent_id)
        if parent:
            info_lines.append(f"[bold]Parent:[/bold]   #{parent.id} {parent.title}")

    console.print(Panel(tree, title="Todo Detail", border_style="blue"))
    console.print("\n".join(info_lines))


def render_stats(store: TodoStore, show_personal: bool = False) -> None:
    today = date.today()
    todos = visible_todos(store, ListFilter.ALL, show_personal=show_personal)
    total = len(todos)
    done = sum(1 for t in todos if t.done)
    active = total - done
    overdue = sum(1 for t in todos if t.is_overdue(today))
    due_today = sum(
        1 for t in todos if t.due_date == today and not t.done
    )

    table = Table(box=box.ROUNDED, show_header=False, padding=(0, 2))
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")

    table.add_row("Total", str(total))
    table.add_row("Active", f"[yellow]{active}[/yellow]")
    table.add_row("Done", f"[green]{done}[/green]")
    table.add_row("Overdue", f"[red]{overdue}[/red]" if overdue else "0")
    table.add_row("Due today", f"[yellow]{due_today}[/yellow]" if due_today else "0")

    console.print(Panel(table, title="td Stats", border_style="blue"))


def print_success(message: str) -> None:
    console.print(f"[bold green]✓[/bold green] {message}")


def print_error(message: str) -> None:
    console.print(f"[bold red]✗[/bold red] {message}")


def print_info(message: str) -> None:
    console.print(f"[dim]→[/dim] {message}")
