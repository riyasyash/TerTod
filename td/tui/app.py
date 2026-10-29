from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from td import __version__
from td.config import load_config, save_config
from td.display import ListFilter, collect_visible_todos, completed_label, due_label, status_icon
from td.limits import add_with_limit
from td.models import DEFAULT_BUCKET, PERSONAL_BUCKET, Todo, TodoStore, TodoStoreLimitError, normalize_bucket
from td.storage import get_data_path, load_store, save_store
from td.sync import SyncError, sync_todos

K9S_CSS = """
Screen {
    background: #0d1117;
}

Header {
    background: #161b22;
    color: #58a6ff;
    text-style: bold;
    dock: top;
    height: 1;
}

Footer {
    background: #161b22;
    color: #8b949e;
    dock: bottom;
    height: 1;
}

#body {
    height: 1fr;
}

#bucket-panel {
    width: 22;
    border-right: solid #30363d;
    background: #0d1117;
}

#bucket-title {
    background: #161b22;
    color: #f778ba;
    text-style: bold;
    padding: 0 1;
    height: 1;
}

BucketList {
    height: 1fr;
    background: #0d1117;
}

OptionList {
    height: 1fr;
    background: #0d1117;
    border: none;
    padding: 0;
}

OptionList > .option-list--option {
    padding: 0 1;
}

OptionList > .option-list--option-highlighted {
    background: #1f6feb;
    color: #ffffff;
    text-style: bold;
}

#main-panel {
    width: 1fr;
}

#context-bar {
    background: #161b22;
    color: #79c0ff;
    padding: 0 1;
    height: 1;
}

#todo-table {
    height: 1fr;
    background: #0d1117;
}

DataTable {
    background: #0d1117;
}

DataTable > .datatable--header {
    background: #161b22;
    color: #f778ba;
    text-style: bold;
}

DataTable > .datatable--cursor {
    background: #1f6feb;
    color: #ffffff;
}

#flash {
    dock: bottom;
    height: 1;
    background: #238636;
    color: #ffffff;
    padding: 0 1;
    display: none;
}

#flash.visible {
    display: block;
}

ModalScreen {
    align: center middle;
}

.dialog {
    width: 70;
    height: auto;
    max-height: 80%;
    border: solid #58a6ff;
    background: #161b22;
    padding: 1 2;
}

.dialog-title {
    text-style: bold;
    color: #58a6ff;
    margin-bottom: 1;
}

.dialog Input {
    margin-bottom: 1;
}

.help-text {
    color: #c9d1d9;
}

.help-key {
    color: #f778ba;
    text-style: bold;
}

.detail-line {
    color: #c9d1d9;
    margin: 0 0 1 0;
}
"""


class HelpScreen(ModalScreen[None]):
    DEFAULT_CSS = K9S_CSS

    BINDINGS = [Binding("escape", "dismiss", "Close"), Binding("q", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        yield Static(
            "\n".join(
                [
                    "[b cyan]td — Keyboard Shortcuts[/]",
                    "",
                    "[pink]Navigation[/]",
                    "  [b]j/k[/] or [b]↑/↓[/]     Move selection",
                    "  [b]tab[/]            Switch bucket ↔ todo list",
                    "  [b]enter[/]          View todo detail",
                    "",
                    "[pink]Actions[/]",
                    "  [b]a[/]              Add todo",
                    "  [b]e[/]              Edit todo (title / due)",
                    "  [b]d[/]              Mark done",
                    "  [b]o[/]              Reopen",
                    "  [b]x[/]              Delete",
                    "  [b]m[/]              Move to bucket",
                    "  [b]s[/]              Git sync",
                    "  [b]r[/]              Refresh",
                    "",
                    "[pink]Views[/]",
                    "  [b]v[/]              Cycle filter (active→all→done→…)",
                    "  [b]c[/]              Completed todos (with dates)",
                    "  [b]p[/]              Toggle personal items (hidden by default)",
                    "  [b]/[/]              Search filter",
                    "  [b]0[/]              All buckets",
                    "  [b]1-9[/]            Jump to bucket",
                    "",
                    "[pink]Commands[/]",
                    "  [b]:[/]              Command line (add, sync, quit…)",
                    "  [b]?[/]              This help",
                    "  [b]q[/]              Quit",
                    "",
                    "[dim]CLI still available: td add, td sync, etc.[/]",
                ]
            ),
            classes="dialog help-text",
        )


class PromptScreen(ModalScreen[Optional[str]]):
    DEFAULT_CSS = K9S_CSS

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, placeholder: str = "") -> None:
        super().__init__()
        self._title = title
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self._title, classes="dialog-title")
            yield Input(placeholder=self._placeholder, id="prompt-input")

    def on_mount(self) -> None:
        self.query_one("#prompt-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


@dataclass
class TodoFormResult:
    title: str
    due_date: date | None = None


def _parse_due_input(raw: str) -> date | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


class AddTodoScreen(ModalScreen[Optional[TodoFormResult]]):
    DEFAULT_CSS = K9S_CSS

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, bucket_label: str) -> None:
        super().__init__()
        self._bucket_label = bucket_label

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("New todo", classes="dialog-title")
            yield Static(f"Bucket: [b]{self._bucket_label}[/]", classes="help-text")
            yield Input(placeholder="What needs doing?", id="title-input")
            yield Input(placeholder="Due date YYYY-MM-DD (optional)", id="due-input")
            yield Static("", id="form-error", classes="help-text")
            yield Static("[dim]tab[/] next field  [dim]enter[/] save  [dim]esc[/] cancel", classes="help-text")

    def on_mount(self) -> None:
        self.query_one("#title-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "title-input":
            self.query_one("#due-input", Input).focus()
        else:
            self._submit()

    def _submit(self) -> None:
        title = self.query_one("#title-input", Input).value.strip()
        due_raw = self.query_one("#due-input", Input).value.strip()
        error = self.query_one("#form-error", Static)
        if not title:
            error.update("[red]Title is required[/]")
            return
        if due_raw:
            due = _parse_due_input(due_raw)
            if due is None:
                error.update("[red]Use YYYY-MM-DD for due date[/]")
                return
        else:
            due = None
        self.dismiss(TodoFormResult(title=title, due_date=due))

    def action_cancel(self) -> None:
        self.dismiss(None)


class EditTodoScreen(ModalScreen[Optional[TodoFormResult]]):
    DEFAULT_CSS = K9S_CSS

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, todo: Todo) -> None:
        super().__init__()
        self._todo = todo

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(f"Edit #{self._todo.id}", classes="dialog-title")
            yield Input(value=self._todo.title, id="title-input")
            due_value = self._todo.due_date.isoformat() if self._todo.due_date else ""
            yield Input(value=due_value, placeholder="Due date YYYY-MM-DD (empty to clear)", id="due-input")
            yield Static("", id="form-error", classes="help-text")
            yield Static("[dim]enter[/] save  [dim]esc[/] cancel", classes="help-text")

    def on_mount(self) -> None:
        self.query_one("#title-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "title-input":
            self.query_one("#due-input", Input).focus()
        else:
            self._submit()

    def _submit(self) -> None:
        title = self.query_one("#title-input", Input).value.strip()
        due_raw = self.query_one("#due-input", Input).value.strip()
        error = self.query_one("#form-error", Static)
        if not title:
            error.update("[red]Title is required[/]")
            return
        if due_raw:
            due = _parse_due_input(due_raw)
            if due is None:
                error.update("[red]Use YYYY-MM-DD for due date[/]")
                return
        else:
            due = None
        self.dismiss(TodoFormResult(title=title, due_date=due))

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    DEFAULT_CSS = K9S_CSS

    BINDINGS = [
        Binding("y", "confirm", "Yes"),
        Binding("n", "cancel", "No"),
        Binding("escape", "cancel", "No"),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self._message, classes="dialog-title")
            yield Static("[y]y[/] confirm  [n] cancel", classes="help-text")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class CommandScreen(ModalScreen[Optional[str]]):
    DEFAULT_CSS = K9S_CSS

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Command", classes="dialog-title")
            yield Input(placeholder="add Buy milk 2026-07-05 | sync | quit", id="cmd-input")
            yield Static(
                "Commands: add, done, reopen, delete, move, sync, bucket, personal, completed, view, refresh, quit",
                classes="help-text",
            )

    def on_mount(self) -> None:
        self.query_one("#cmd-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class DetailScreen(ModalScreen[None]):
    DEFAULT_CSS = K9S_CSS

    BINDINGS = [Binding("escape", "dismiss", "Close"), Binding("q", "dismiss", "Close")]

    def __init__(self, store: TodoStore, todo: Todo) -> None:
        super().__init__()
        self._store = store
        self._todo = todo

    def compose(self) -> ComposeResult:
        todo = self._todo
        children = self._store.children_of(todo.id)
        lines = [
            f"[b cyan]#{todo.id}[/] {todo.title}",
            "",
            f"[pink]Bucket[/]    {todo.bucket}",
            f"[pink]Status[/]    {'done' if todo.done else 'active'}",
            f"[pink]Due[/]        {due_label(todo)}",
            f"[pink]Created[/]   {todo.created_at.strftime('%b %d %H:%M')}",
        ]
        if todo.completed_at:
            lines.append(f"[pink]Completed[/] {todo.completed_at.strftime('%b %d %H:%M')}")
        if todo.parent_id:
            parent = self._store.get(todo.parent_id)
            if parent:
                lines.append(f"[pink]Parent[/]    #{parent.id} {parent.title}")
        if children:
            lines.append("")
            lines.append("[pink]Sub-todos[/]")
            for child in children:
                icon = status_icon(child)
                strike = "[strike]" if child.done else ""
                end = "[/strike]" if child.done else ""
                lines.append(f"  {strike}[{icon}] #{child.id} {child.title}{end}")

        with Vertical(classes="dialog"):
            yield Static("\n".join(lines), classes="detail-line")


class BucketList(OptionList):
    pass


class TdApp(App[None]):
    """k9s-inspired todo browser."""

    TITLE = "td"
    CSS = K9S_CSS

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help", show=False),
        Binding("slash", "search", "Filter", show=False),
        Binding("colon", "command", "Cmd", show=False),
        Binding("a", "add_todo", "Add"),
        Binding("e", "edit_todo", "Edit"),
        Binding("d", "done", "Done"),
        Binding("o", "reopen", "Open"),
        Binding("x", "delete", "Del"),
        Binding("m", "move", "Move"),
        Binding("s", "sync", "Sync"),
        Binding("r", "refresh", "Refresh"),
        Binding("v", "cycle_view", "View"),
        Binding("c", "show_completed", "Done"),
        Binding("p", "toggle_personal", "Personal"),
        Binding("enter", "detail", "Detail", show=False),
        Binding("0", "all_buckets", "All", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        config = load_config()
        self.show_personal = config.show_personal
        self.store = load_store()
        self.view = ListFilter.ACTIVE
        self.bucket_filter: str | None = None
        self.search_text = ""
        self._row_keys: list[int] = []
        self._bucket_reload = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="bucket-panel"):
                yield Static(" BUCKETS ", id="bucket-title")
                yield BucketList(id="bucket-list")
            with Vertical(id="main-panel"):
                yield Static("", id="context-bar")
                yield DataTable(id="todo-table", cursor_type="row", zebra_stripes=True)
        yield Static("", id="flash")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#todo-table", DataTable)
        table.add_columns("", "ID", "TASK", "DUE", "BUCKET")
        table.focus()
        self.refresh_view()

    def _reload_buckets(self) -> None:
        bucket_list = self.query_one("#bucket-list", BucketList)
        self._bucket_reload = True
        try:
            bucket_list.clear_options()
            bucket_list.add_option(Option("all", id="bucket-all"))
            for bucket in self.store.bucket_order():
                count = sum(1 for t in self.store.todos if t.bucket == bucket and not t.done)
                label = bucket
                if bucket == PERSONAL_BUCKET and not self.show_personal and self.bucket_filter != PERSONAL_BUCKET:
                    label = f"{bucket} ({count}) · hidden"
                else:
                    label = f"{bucket} ({count})"
                bucket_list.add_option(Option(label, id=f"bucket-{bucket}"))

            target = f"bucket-{self.bucket_filter}" if self.bucket_filter else "bucket-all"
            for index, opt in enumerate(bucket_list.options):
                if opt.id == target:
                    bucket_list.highlighted = index
                    break
        finally:
            self._bucket_reload = False

    def _bucket_index(self, bucket: str) -> int:
        buckets = ["all", *self.store.bucket_order()]
        try:
            return buckets.index(bucket)
        except ValueError:
            return 0

    def _update_context_bar(self) -> None:
        bucket = self.bucket_filter or "all"
        view = self.view.value
        search = f"  /{self.search_text}" if self.search_text else ""
        if self.bucket_filter == PERSONAL_BUCKET or self.show_personal:
            personal_state = "[green]personal: shown[/]"
        else:
            personal_state = "[dim]personal: hidden[/] [dim](p to show)[/]"
        sync_cfg = load_config().sync
        sync_hint = f"  [dim]sync: {sync_cfg.remote}[/]" if sync_cfg else ""
        path = get_data_path()
        self.query_one("#context-bar", Static).update(
            f" View: [b]{view}[/]  Bucket: [b]{bucket}[/]  {personal_state}{search}  [dim]{path}[/]{sync_hint}"
        )

    def refresh_table(self) -> None:
        table = self.query_one("#todo-table", DataTable)
        table.clear(columns=True)
        show_completed = self.view == ListFilter.DONE
        if show_completed:
            table.add_columns("", "ID", "TASK", "COMPLETED", "BUCKET")
        else:
            table.add_columns("", "ID", "TASK", "DUE", "BUCKET")

        items = collect_visible_todos(
            self.store, self.view, self.bucket_filter, self.show_personal
        )
        self._row_keys = []
        for todo, depth in items:
            if self.search_text and self.search_text.lower() not in todo.title.lower():
                continue
            indent = "  " * depth + ("└ " if depth else "")
            title = todo.title
            if todo.done:
                title = f"[strike]{title}[/strike]"
            date_col = completed_label(todo) if show_completed else due_label(todo)
            table.add_row(
                status_icon(todo),
                str(todo.id),
                indent + title,
                date_col,
                todo.bucket,
                key=str(todo.id),
            )
            self._row_keys.append(todo.id)

        self._update_context_bar()

    def refresh_view(self) -> None:
        self.store = load_store()
        self.refresh_table()
        self._reload_buckets()

    def flash(self, message: str, *, error: bool = False) -> None:
        bar = self.query_one("#flash", Static)
        bar.remove_class("visible")
        bar.styles.background = "#da3633" if error else "#238636"
        bar.update(f" {message}")
        bar.add_class("visible")
        self.set_timer(2.5, lambda: bar.remove_class("visible"))

    def _selected_todo_id(self) -> int | None:
        table = self.query_one("#todo-table", DataTable)
        if table.row_count == 0:
            return None
        coord = table.cursor_coordinate
        if coord is None:
            return None
        row, _ = coord
        if row >= len(self._row_keys):
            return None
        return self._row_keys[row]

    def _persist(self) -> None:
        save_store(self.store)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id:
            self._apply_bucket_selection(event.option.id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self._apply_bucket_selection(event.option.id)
            self.query_one("#todo-table", DataTable).focus()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_refresh(self) -> None:
        self.refresh_view()
        self.flash("Refreshed")

    def _apply_bucket_selection(self, item_id: str) -> None:
        if self._bucket_reload:
            return
        if item_id == "bucket-all":
            self.bucket_filter = None
        elif item_id.startswith("bucket-"):
            self.bucket_filter = item_id.removeprefix("bucket-")
        self.refresh_table()

    def action_all_buckets(self) -> None:
        self.bucket_filter = None
        bucket_list = self.query_one("#bucket-list", BucketList)
        bucket_list.highlighted = 0
        self.refresh_table()

    def action_cycle_view(self) -> None:
        order = [
            ListFilter.ACTIVE,
            ListFilter.ALL,
            ListFilter.DONE,
            ListFilter.OVERDUE,
            ListFilter.TODAY,
        ]
        idx = order.index(self.view)
        self.view = order[(idx + 1) % len(order)]
        self.refresh_table()
        self.flash(f"View: {self.view.value}")

    def action_toggle_personal(self) -> None:
        self.show_personal = not self.show_personal
        config = load_config()
        config.show_personal = self.show_personal
        save_config(config)
        self.refresh_view()
        state = "shown" if self.show_personal else "hidden"
        self.flash(f"Personal items {state}")

    def action_show_completed(self) -> None:
        self.view = ListFilter.DONE
        self.refresh_table()
        self.flash("Completed todos (newest first)")

    def action_search(self) -> None:
        def apply(result: str | None) -> None:
            self.search_text = result or ""
            self.refresh_table()

        self.push_screen(PromptScreen("Filter todos", "/search term"), apply)

    def action_command(self) -> None:
        self.push_screen(CommandScreen(), self._run_command)

    def _run_command(self, cmd_line: str | None) -> None:
        if not cmd_line:
            return
        parts = cmd_line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in {"quit", "q", "exit"}:
            self.exit()
        elif cmd == "refresh":
            self.action_refresh()
        elif cmd == "sync":
            self.action_sync()
        elif cmd == "view" and arg:
            try:
                self.view = ListFilter(arg.lower())
                self.refresh_view()
                self.flash(f"View: {self.view.value}")
            except ValueError:
                self.flash(f"Unknown view: {arg}", error=True)
        elif cmd == "personal":
            if arg in {"on", "show", "true", "1"}:
                self.show_personal = True
            elif arg in {"off", "hide", "false", "0"}:
                self.show_personal = False
            else:
                self.show_personal = not self.show_personal
            config = load_config()
            config.show_personal = self.show_personal
            save_config(config)
            self.refresh_view()
            self.flash(f"Personal items {'shown' if self.show_personal else 'hidden'}")
        elif cmd == "completed":
            self.action_show_completed()
        elif cmd == "bucket" and arg:
            self.bucket_filter = normalize_bucket(arg)
            self.refresh_view()
            self.flash(f"Bucket: {self.bucket_filter}")
        elif cmd == "add" and arg:
            self._create_todo_from_command(arg)
        elif cmd == "done" and arg.isdigit():
            self._mark_done(int(arg))
        elif cmd == "reopen" and arg.isdigit():
            self._reopen(int(arg))
        elif cmd == "delete" and arg.isdigit():
            self._delete(int(arg))
        elif cmd == "move" and " " in arg:
            tid_s, bucket = arg.split(maxsplit=1)
            if tid_s.isdigit():
                self._move(int(tid_s), bucket)
        else:
            self.flash("Unknown command. Try: add, sync, bucket, view, quit", error=True)

    def action_add_todo(self) -> None:
        bucket = self.bucket_filter or DEFAULT_BUCKET
        self.push_screen(AddTodoScreen(bucket), self._apply_add_form)

    def _apply_add_form(self, result: TodoFormResult | None) -> None:
        if result is None:
            return
        self._create_todo(result.title, due_date=result.due_date)

    def _create_todo_from_command(self, arg: str) -> None:
        parts = arg.rsplit(maxsplit=1)
        if len(parts) == 2:
            maybe_date = _parse_due_input(parts[1])
            if maybe_date is not None:
                self._create_todo(parts[0], due_date=maybe_date)
                return
        self._create_todo(arg)

    def _create_todo(self, title: str, due_date: date | None = None) -> None:
        if not title:
            return
        bucket = self.bucket_filter
        try:
            todo = add_with_limit(self.store, title, bucket=bucket, due_date=due_date)
        except TodoStoreLimitError as exc:
            self.flash(str(exc), error=True)
            return
        self._persist()
        self.refresh_view()
        due_note = f", due {due_date.strftime('%b %d')}" if due_date else ""
        self.flash(f"Added #{todo.id} → {todo.bucket}{due_note}")

    def action_edit_todo(self) -> None:
        todo_id = self._selected_todo_id()
        if todo_id is None:
            self.flash("No todo selected", error=True)
            return
        todo = self.store.get(todo_id)
        if not todo:
            return

        def apply(result: TodoFormResult | None) -> None:
            if result is None:
                return
            todo.title = result.title
            todo.due_date = result.due_date
            todo.touch()
            self._persist()
            self.refresh_view()
            self.flash(f"Updated #{todo.id}")

        self.push_screen(EditTodoScreen(todo), apply)

    def action_done(self) -> None:
        todo_id = self._selected_todo_id()
        if todo_id is None:
            self.flash("No todo selected", error=True)
            return
        self._mark_done(todo_id)

    def _mark_done(self, todo_id: int) -> None:
        try:
            todo = self.store.mark_done(todo_id)
        except KeyError:
            self.flash(f"Todo #{todo_id} not found", error=True)
            return
        self._persist()
        self.refresh_view()
        self.flash(f"Done #{todo_id}: {todo.title}")

    def action_reopen(self) -> None:
        todo_id = self._selected_todo_id()
        if todo_id is None:
            self.flash("No todo selected", error=True)
            return
        self._reopen(todo_id)

    def _reopen(self, todo_id: int) -> None:
        try:
            todo = self.store.reopen(todo_id)
        except KeyError:
            self.flash(f"Todo #{todo_id} not found", error=True)
            return
        self._persist()
        self.refresh_view()
        self.flash(f"Reopened #{todo_id}: {todo.title}")

    def action_delete(self) -> None:
        todo_id = self._selected_todo_id()
        if todo_id is None:
            self.flash("No todo selected", error=True)
            return
        todo = self.store.get(todo_id)
        if not todo:
            return

        def confirm(ok: bool) -> None:
            if ok:
                self._delete(todo_id)

        self.push_screen(ConfirmScreen(f"Delete #{todo_id} {todo.title}?"), confirm)

    def _delete(self, todo_id: int) -> None:
        todo = self.store.get(todo_id)
        if todo is None:
            self.flash(f"Todo #{todo_id} not found", error=True)
            return
        removed = self.store.remove(todo_id)
        self._persist()
        self.refresh_view()
        self.flash(f"Removed {len(removed)} todo(s)")

    def action_move(self) -> None:
        todo_id = self._selected_todo_id()
        if todo_id is None:
            self.flash("No todo selected", error=True)
            return

        def pick(bucket: str | None) -> None:
            if bucket:
                self._move(todo_id, bucket)

        buckets = ", ".join(self.store.bucket_order())
        self.push_screen(PromptScreen("Move to bucket", buckets), pick)

    def _move(self, todo_id: int, bucket: str) -> None:
        bucket = normalize_bucket(bucket)
        self.store.ensure_bucket(bucket)
        try:
            todo = self.store.move_to_bucket(todo_id, bucket)
        except KeyError:
            self.flash(f"Todo #{todo_id} not found", error=True)
            return
        self._persist()
        self.refresh_view()
        self.flash(f"Moved #{todo_id} → {todo.bucket}")

    def action_sync(self) -> None:
        try:
            result = sync_todos()
        except SyncError as exc:
            self.flash(str(exc), error=True)
            return
        self.refresh_view()
        self.flash(result.message)

    def action_detail(self) -> None:
        todo_id = self._selected_todo_id()
        if todo_id is None:
            return
        todo = self.store.get(todo_id)
        if todo:
            self.push_screen(DetailScreen(self.store, todo))

    def on_key(self, event) -> None:
        if event.key.isdigit() and event.key != "0":
            idx = int(event.key)
            buckets = self.store.bucket_order()
            if idx <= len(buckets):
                self.bucket_filter = buckets[idx - 1]
                bucket_list = self.query_one("#bucket-list", BucketList)
                bucket_list.highlighted = idx
                self.refresh_table()


def run_tui() -> None:
    app = TdApp()
    app.run()
