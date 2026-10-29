# td

A clean, terminal-based todo app with sub-todos, due dates, and JSON persistence.

## Install

### Homebrew (personal tap)

Once added to your Homebrew tap:

```bash
brew install td
```

See [packaging/homebrew/td.rb.example](packaging/homebrew/td.rb.example) for the formula template.

### From GitHub

```bash
pip install git+https://github.com/riyasyash/td.git
```

Or install a tagged release:

```bash
pip install https://github.com/riyasyash/td/archive/refs/tags/v0.0.1.tar.gz
```

### Development

Homebrew Python blocks system-wide `pip install`. Use a virtual environment:

```bash
git clone https://github.com/riyasyash/td.git
cd td
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Then run `td` while the venv is active. To leave the venv: `deactivate`.

**Optional — use without activating each time:**

```bash
alias td="/path/to/td/.venv/bin/td"
```

Then run `td` to open the interactive UI (k9s-style). Use `td --cli` for a one-shot terminal list.

## Interactive UI (k9s-style)

Running `td` with no arguments launches a full-screen TUI:

```
┌─ td ─────────────────────────────────────────────────┐
│ BUCKETS │  ○  ID  TASK              DUE    BUCKET         │
│ all     │  ○   1  Deploy app        —      work           │
│ work ◄  │  ○   5    └ Write tests   —      work           │
│ personal│  !   3  Fix outage        !Jun28 priority        │
├─────────┴──────────────────────────────────────────────────┤
│ <a>dd <d>one <o>pen <x>del <m>ove <s>ync <v>iew <:>cmd <?> │
└──────────────────────────────────────────────────────────┘
```

| Key | Action |
|-----|--------|
| `j/k` `↑/↓` | Navigate |
| `tab` | Switch bucket list ↔ todos |
| `a` | Add todo |
| `e` | Edit title / due date |
| `d` | Mark done |
| `o` | Reopen |
| `x` | Delete |
| `m` | Move bucket |
| `s` | Git sync |
| `v` | Cycle view (active/all/done/overdue/today) |
| `c` | Completed todos with completion date |
| `p` | Toggle personal items (hidden by default) |
| `/` | Search filter |
| `:` | Command line (`add`, `sync`, `bucket work`, `quit`) |
| `0` `1-9` | Jump to bucket |
| `enter` | Todo detail |
| `?` | Help |
| `q` | Quit |

CLI commands still work for scripting: `td add "task"`, `td sync`, etc.

## Quick start

```bash
# Add todos
td add "Buy groceries"
td add "Finish report" --due 2026-07-05

# Add sub-todos
td sub 1 "Milk"
td sub 1 "Eggs" --due 2026-07-01

# List todos (default: active only)
td
td list
td list --filter overdue
td list --filter today
td list --filter done
td list --filter all

# Manage todos
td done 1
td reopen 1
td edit 2 --title "Updated title" --due 2026-07-10
td edit 2 --clear-due
td show 1
td remove 1 --force

# Utilities
td stats
td clear --force
td path
```

## Commands

| Command | Description |
|---------|-------------|
| `td` | List active todos (default) |
| `add` | Add a new todo |
| `sub` | Add a sub-todo under a parent |
| `done` | Mark a todo as complete |
| `reopen` | Reopen a completed todo |
| `remove` | Remove a todo (and sub-todos with `--force`) |
| `list` | List todos with filters |
| `show` | Show todo details and sub-todo tree |
| `edit` | Edit title, due date, or bucket |
| `move` | Move a todo to another bucket |
| `clear` | Remove all completed todos |
| `stats` | Show summary statistics |
| `path` | Show JSON storage location |
| `bucket` | List or add buckets |
| `remote` | Configure a private git repo for sync |
| `sync` | Pull, merge, and push todos with git |

## Git sync

Keep your todos in a **private** git repo and sync across machines:

```bash
# 1. Create an empty private repo on GitHub/GitLab, then:
td remote set git@github.com:you/td-private.git

# 2. Sync (pull → merge → commit → push)
td sync

# Preview changes without writing
td sync --dry-run

# Check pending changes
td sync status

# View or remove remote config
td remote show
td remote unset
```

Sync merges todos by stable `uid`, keeping the most recently updated version of each item. Deletions propagate across devices.

Config lives at `~/.td/config.json`. The repo is cloned to `~/.td/repo` by default.

## Buckets

Built-in buckets: **work** (shown by default) and **personal** (default for new todos). Custom buckets can be added with `td bucket add`.

**Personal items are hidden by default** so work todos stay front and center during the day. Show them when needed:

```bash
td list --show-personal          # or -p
td stats --show-personal
td --cli --show-personal
```

In the TUI, press **`p`** to toggle personal visibility (saved in `~/.td/config.json`). Select the **personal** bucket in the sidebar to view personal items without toggling globally.

**Completed todos:** press **`c`** in the TUI, or `td list --filter done` — shows completion date/time, newest first.

```bash
td add "Deploy release" --bucket work
td add "Call dentist" --bucket personal

td list --bucket personal        # always shows personal when filtered
td list --filter done
td move 3 personal

td bucket list
```

Lists are grouped by bucket (except the completed view, which is a flat dated list). Sub-todos inherit their parent's bucket unless you override with `--bucket`.

## Filters

Use `--filter` / `-f` with `list`:

- `active` — open todos (default)
- `all` — everything
- `done` — completed todos
- `overdue` — past due and still open
- `today` — due today

## Data storage

Todos are saved to `~/.td/todos.json` by default. Override with:

```bash
export TD_DATA=/path/to/todos.json
```

## Icons

| Icon | Meaning |
|------|---------|
| `○` | Active |
| `✓` | Done |
| `!` | Overdue |
| `◉` | Due today |

## Releasing

1. Bump `__version__` in `td/__init__.py`.
2. Commit and push to `main`.
3. Tag and push: `git tag v0.0.1 && git push origin v0.0.1`
4. GitHub Actions builds the sdist/wheel and attaches them to the release.
5. Update the `sha256` in your Homebrew formula using the release tarball.
