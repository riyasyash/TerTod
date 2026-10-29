from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from td import __version__
from td.config import DEFAULT_MAX_TODOS, SyncConfig, load_config, save_config
from td.display import (
    ListFilter,
    print_error,
    print_info,
    print_success,
    render_bucket_list,
    render_stats,
    render_todo_detail,
    render_todo_list,
)
from td.limits import add_with_limit
from td.models import TodoStoreLimitError, normalize_bucket
from td.storage import get_data_path, load_store, save_store
from td.sync import SyncError, sync_status, sync_todos

app = typer.Typer(
    name="td",
    help="td — a clean terminal todo app with sub-todos and due dates.",
    no_args_is_help=False,
    rich_markup_mode="rich",
)

console = Console()

remote_app = typer.Typer(help="Manage a private git repo for todo sync.")
sync_app = typer.Typer(help="Sync todos with your private git repo.")
bucket_app = typer.Typer(help="Manage todo buckets.")
config_app = typer.Typer(help="App configuration.")
app.add_typer(remote_app, name="remote")
app.add_typer(sync_app, name="sync")
app.add_typer(bucket_app, name="bucket")
app.add_typer(config_app, name="config")


def _parse_due(due: Optional[str]) -> date:
    if due is None:
        raise typer.BadParameter("Due date is required.")
    try:
        return date.fromisoformat(due)
    except ValueError as exc:
        raise typer.BadParameter(
            f"Invalid date '{due}'. Use YYYY-MM-DD format."
        ) from exc


def _get_todo_or_exit(store, todo_id: int):
    todo = store.get(todo_id)
    if todo is None:
        print_error(f"Todo #{todo_id} not found.")
        raise typer.Exit(1)
    return todo


def _resolve_bucket(store, bucket: str, create: bool = False) -> str:
    bucket = normalize_bucket(bucket)
    if bucket not in store.buckets:
        if create:
            return store.ensure_bucket(bucket)
        known = ", ".join(store.buckets)
        print_error(f"Unknown bucket '{bucket}'. Known buckets: {known}")
        print_info("Add a custom bucket with: td bucket add <name>")
        raise typer.Exit(1)
    return bucket


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", "-V", help="Show version and exit."),
    ] = False,
    cli: Annotated[
        bool,
        typer.Option("--cli", help="Print list to terminal instead of launching the TUI."),
    ] = False,
    show_personal: Annotated[
        bool,
        typer.Option("--show-personal", "-p", help="Include personal-bucket todos in the list."),
    ] = False,
):
    if version:
        console.print(f"td v{__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        if cli:
            store = load_store()
            render_todo_list(store, ListFilter.ACTIVE, show_personal=show_personal)
        else:
            from td.tui import run_tui

            run_tui()


@app.command("tui")
def launch_tui():
    """Launch the interactive k9s-style UI."""
    from td.tui import run_tui

    run_tui()


@app.command("add")
def add_todo(
    title: Annotated[str, typer.Argument(help="What needs to be done.")],
    due: Annotated[
        Optional[str],
        typer.Option("--due", "-d", help="Due date (YYYY-MM-DD)."),
    ] = None,
    parent: Annotated[
        Optional[int],
        typer.Option("--parent", "-p", help="Parent todo ID for a sub-todo."),
    ] = None,
    bucket: Annotated[
        Optional[str],
        typer.Option("--bucket", "-b", help="Bucket: work, personal."),
    ] = None,
):
    """Add a new todo."""
    store = load_store()
    due_date = _parse_due(due) if due else None

    if parent is not None:
        _get_todo_or_exit(store, parent)
    if bucket is not None:
        _resolve_bucket(store, bucket, create=True)

    try:
        todo = add_with_limit(store, title, parent_id=parent, due_date=due_date, bucket=bucket)
    except TodoStoreLimitError as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc
    save_store(store)

    label = f"#{todo.id} {todo.title}"
    if parent:
        print_success(f"Added sub-todo {label} under #{parent}")
    else:
        print_success(f"Added {label}")
    print_info(f"Bucket: {todo.bucket}")
    if due_date:
        print_info(f"Due {due_date.strftime('%b %d, %Y')}")


@app.command("sub")
def add_sub_todo(
    parent_id: Annotated[int, typer.Argument(help="Parent todo ID.")],
    title: Annotated[str, typer.Argument(help="Sub-todo title.")],
    due: Annotated[
        Optional[str],
        typer.Option("--due", "-d", help="Due date (YYYY-MM-DD)."),
    ] = None,
    bucket: Annotated[
        Optional[str],
        typer.Option("--bucket", "-b", help="Bucket (defaults to parent's bucket)."),
    ] = None,
):
    """Add a sub-todo under an existing todo."""
    store = load_store()
    _get_todo_or_exit(store, parent_id)
    due_date = _parse_due(due) if due else None
    if bucket is not None:
        _resolve_bucket(store, bucket, create=True)

    try:
        todo = add_with_limit(
            store, title, parent_id=parent_id, due_date=due_date, bucket=bucket
        )
    except TodoStoreLimitError as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc
    save_store(store)

    print_success(f"Added sub-todo #{todo.id} under #{parent_id}: {title}")


@app.command("done")
def mark_done(
    todo_id: Annotated[int, typer.Argument(help="Todo ID to mark complete.")],
    no_cascade: Annotated[
        bool,
        typer.Option("--no-cascade", help="Don't mark sub-todos as done."),
    ] = False,
):
    """Mark a todo as done."""
    store = load_store()
    try:
        todo = store.mark_done(todo_id, recursive=not no_cascade)
    except KeyError:
        print_error(f"Todo #{todo_id} not found.")
        raise typer.Exit(1)

    save_store(store)
    print_success(f"Marked #{todo_id} as done: {todo.title}")


@app.command("reopen")
def reopen_todo(
    todo_id: Annotated[int, typer.Argument(help="Todo ID to reopen.")],
):
    """Reopen a completed todo."""
    store = load_store()
    try:
        todo = store.reopen(todo_id)
    except KeyError:
        print_error(f"Todo #{todo_id} not found.")
        raise typer.Exit(1)

    save_store(store)
    print_success(f"Reopened #{todo_id}: {todo.title}")


@app.command("remove")
def remove_todo(
    todo_id: Annotated[int, typer.Argument(help="Todo ID to remove.")],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation."),
    ] = False,
):
    """Remove a todo and its sub-todos."""
    store = load_store()
    todo = _get_todo_or_exit(store, todo_id)

    descendants = store.descendants_of(todo_id)
    if descendants and not force:
        print_error(
            f"Todo #{todo_id} has {len(descendants)} sub-todo(s). "
            "Use --force to remove them too."
        )
        raise typer.Exit(1)

    removed = store.remove(todo_id)
    save_store(store)
    print_success(f"Removed {len(removed)} todo(s), including #{todo_id}: {todo.title}")


@app.command("list")
def list_todos(
    filter: Annotated[
        ListFilter,
        typer.Option(
            "--filter",
            "-f",
            help="Filter todos: all, active, done, overdue, today.",
            case_sensitive=False,
        ),
    ] = ListFilter.ACTIVE,
    bucket: Annotated[
        Optional[str],
        typer.Option("--bucket", "-b", help="Show only todos in this bucket."),
    ] = None,
    show_personal: Annotated[
        bool,
        typer.Option("--show-personal", "-p", help="Include personal-bucket todos."),
    ] = False,
):
    """List todos."""
    store = load_store()
    if bucket is not None:
        _resolve_bucket(store, bucket)
    render_todo_list(store, filter, bucket_filter=bucket, show_personal=show_personal)


@app.command("move")
def move_todo(
    todo_id: Annotated[int, typer.Argument(help="Todo ID to move.")],
    to: Annotated[str, typer.Argument(help="Destination bucket.")],
    no_cascade: Annotated[
        bool,
        typer.Option("--no-cascade", help="Don't move sub-todos."),
    ] = False,
):
    """Move a todo (and its sub-todos) to another bucket."""
    store = load_store()
    _get_todo_or_exit(store, todo_id)
    bucket = _resolve_bucket(store, to, create=True)
    descendants = store.descendants_of(todo_id)

    try:
        todo = store.move_to_bucket(todo_id, bucket, cascade=not no_cascade)
    except KeyError:
        print_error(f"Todo #{todo_id} not found.")
        raise typer.Exit(1)

    save_store(store)
    if no_cascade:
        print_success(f"Moved #{todo_id} to {bucket}: {todo.title}")
    else:
        print_success(
            f"Moved #{todo_id} and {len(descendants)} sub-todo(s) to {bucket}: {todo.title}"
        )


@app.command("show")
def show_todo(
    todo_id: Annotated[int, typer.Argument(help="Todo ID to show.")],
):
    """Show details for a todo."""
    store = load_store()
    todo = _get_todo_or_exit(store, todo_id)
    render_todo_detail(store, todo)


@app.command("edit")
def edit_todo(
    todo_id: Annotated[int, typer.Argument(help="Todo ID to edit.")],
    title: Annotated[
        Optional[str],
        typer.Option("--title", "-t", help="New title."),
    ] = None,
    due: Annotated[
        Optional[str],
        typer.Option("--due", "-d", help="New due date (YYYY-MM-DD)."),
    ] = None,
    clear_due: Annotated[
        bool,
        typer.Option("--clear-due", help="Remove the due date."),
    ] = False,
    bucket: Annotated[
        Optional[str],
        typer.Option("--bucket", "-b", help="Move to a different bucket."),
    ] = None,
):
    """Edit a todo's title, due date, or bucket."""
    store = load_store()
    todo = _get_todo_or_exit(store, todo_id)

    if title is None and due is None and not clear_due and bucket is None:
        print_error("Provide --title, --due, --clear-due, or --bucket.")
        raise typer.Exit(1)

    if title:
        todo.title = title
    if clear_due:
        todo.due_date = None
    elif due:
        todo.due_date = _parse_due(due)
    if bucket is not None:
        resolved = _resolve_bucket(store, bucket, create=True)
        todo.bucket = resolved

    todo.touch()
    save_store(store)
    print_success(f"Updated #{todo_id}: {todo.title}")


@app.command("clear")
def clear_done(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation."),
    ] = False,
):
    """Remove all completed todos."""
    store = load_store()
    done_todos = [t for t in store.todos if t.done]

    if not done_todos:
        print_info("No completed todos to clear.")
        raise typer.Exit()

    if not force:
        print_error(f"{len(done_todos)} completed todo(s) will be removed. Use --force to confirm.")
        raise typer.Exit(1)

    done_ids = {t.id for t in done_todos}
    # Reparent any active sub-todos whose parent is being cleared so they
    # don't become orphaned (and invisible) after the clear.
    for todo in store.todos:
        if not todo.done and todo.parent_id in done_ids:
            todo.parent_id = None
            todo.parent_uid = None
            todo.touch()

    now = datetime.now()
    for todo in done_todos:
        store.deletions[todo.uid] = now
    store.todos = [t for t in store.todos if not t.done]
    save_store(store)
    print_success(f"Cleared {len(done_todos)} completed todo(s)")


@app.command("stats")
def show_stats(
    show_personal: Annotated[
        bool,
        typer.Option("--show-personal", "-p", help="Include personal-bucket todos."),
    ] = False,
):
    """Show todo statistics."""
    store = load_store()
    render_stats(store, show_personal=show_personal)


@app.command("path")
def show_path():
    """Show where todos are stored."""
    path = get_data_path()
    print_info(str(path))


@remote_app.command("set")
def remote_set(
    url: Annotated[str, typer.Argument(help="Git remote URL (SSH or HTTPS).")],
    branch: Annotated[
        str,
        typer.Option("--branch", "-b", help="Branch to sync."),
    ] = "main",
    file: Annotated[
        str,
        typer.Option("--file", help="Todo JSON filename inside the repo."),
    ] = "todos.json",
    dir: Annotated[
        Optional[Path],
        typer.Option("--dir", help="Local clone directory."),
    ] = None,
):
    """Point td at a private git repo for sync."""
    from td.config import DEFAULT_SYNC_DIR

    sync = SyncConfig(
        remote=url,
        branch=branch,
        file=file,
        dir=dir or DEFAULT_SYNC_DIR,
    )
    config = load_config()
    config.sync = sync
    save_config(config)
    print_success(f"Remote set to {url}")
    print_info(f"Branch: {branch}  File: {file}  Clone: {sync.dir}")


@remote_app.command("show")
def remote_show():
    """Show the configured git remote."""
    config = load_config()
    if config.sync is None:
        print_info("No git remote configured. Run: td remote set <git-url>")
        raise typer.Exit()

    sync = config.sync
    table = Table(show_header=False, padding=(0, 2))
    table.add_row("Remote", sync.remote)
    table.add_row("Branch", sync.branch)
    table.add_row("File", sync.file)
    table.add_row("Clone dir", str(sync.dir))
    if sync.last_synced_at:
        table.add_row("Last synced", sync.last_synced_at.strftime("%b %d, %Y %H:%M"))
    console.print(Panel(table, title="Git Remote", border_style="blue"))


@remote_app.command("unset")
def remote_unset():
    """Remove git remote configuration."""
    config = load_config()
    if config.sync is None:
        print_info("No git remote configured.")
        raise typer.Exit()

    config.sync = None
    save_config(config)
    print_success("Git remote removed. Local todos are unchanged.")


@sync_app.callback(invoke_without_command=True)
def sync_run(
    ctx: typer.Context,
    message: Annotated[
        str,
        typer.Option("--message", "-m", help="Git commit message."),
    ] = "chore: sync todos",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview merge without writing or pushing."),
    ] = False,
):
    """Pull, merge, and push todos with your private git repo."""
    if ctx.invoked_subcommand is not None:
        return

    try:
        result = sync_todos(message=message, dry_run=dry_run)
    except SyncError as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc

    if dry_run:
        print_info(result.message)
    else:
        print_success(result.message)


@sync_app.command("status")
def sync_status_cmd():
    """Show sync configuration and pending changes."""
    try:
        info = sync_status()
    except SyncError as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc

    if not info["configured"]:
        print_info("No git remote configured. Run: td remote set <git-url>")
        raise typer.Exit()

    table = Table(show_header=False, padding=(0, 2))
    table.add_row("Remote", info["remote"])
    table.add_row("Branch", info["branch"])
    table.add_row("Local file", info["local_path"])
    table.add_row("Local todos", str(info["local_count"]))
    table.add_row("Remote todos", str(info.get("remote_count", "—")))
    if info.get("last_synced_at"):
        table.add_row("Last synced", info["last_synced_at"])

    if info.get("in_sync"):
        table.add_row("Status", "[green]in sync[/green]")
    else:
        pending = (
            f"+{info.get('pending_adds', 0)} "
            f"~{info.get('pending_updates', 0)} "
            f"-{info.get('pending_removals', 0)}"
        )
        table.add_row("Pending", f"[yellow]{pending}[/yellow] (add / update / remove)")

    console.print(Panel(table, title="Sync Status", border_style="blue"))


@bucket_app.command("list")
def bucket_list():
    """List buckets and todo counts."""
    store = load_store()
    render_bucket_list(store)


@bucket_app.command("add")
def bucket_add(
    name: Annotated[str, typer.Argument(help="New bucket name.")],
):
    """Add a custom bucket."""
    store = load_store()
    bucket = store.ensure_bucket(name)
    save_store(store)
    print_success(f"Bucket '{bucket}' is ready to use.")


@config_app.command("show")
def config_show():
    """Show app configuration."""
    config = load_config()
    table = Table(show_header=False, padding=(0, 2))
    table.add_row("Max todos", str(config.max_todos))
    table.add_row("Show personal (TUI)", "yes" if config.show_personal else "no")
    if config.sync:
        table.add_row("Git remote", config.sync.remote)
    else:
        table.add_row("Git remote", "not configured")
    console.print(Panel(table, title="Configuration", border_style="blue"))


@config_app.command("set-max-todos")
def config_set_max_todos(
    limit: Annotated[int, typer.Argument(help="Maximum todos (active cap and cleanup threshold).")],
):
    """Set the maximum number of todos."""
    if limit < 1:
        print_error("max_todos must be at least 1.")
        raise typer.Exit(1)

    config = load_config()
    config.max_todos = limit
    save_config(config)
    print_success(f"Max todos set to {limit}")
    if limit != DEFAULT_MAX_TODOS:
        print_info(f"Default is {DEFAULT_MAX_TODOS}. Completed todos are removed oldest-first when over this limit.")


if __name__ == "__main__":
    app()
