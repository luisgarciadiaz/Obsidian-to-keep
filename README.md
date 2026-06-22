# Obsidian ↔ Keep Sync

Bidirectional synchronization between Google Keep and an Obsidian vault.

## Features

- **Bidirectional sync** — changes in Obsidian → Keep, changes in Keep → Obsidian
- **Markdown fidelity** — headings, bold, lists, tasks, code blocks, callouts, wikilinks
- **Conflict resolution** — configurable strategy (newer wins, Keep wins, Obsidian wins, duplicate)
- **File watching** — watchdog monitors Obsidian vault for instant sync (optional)
- **Inbox workflow** — new Keep notes with `obsidian-inbox` label become `.md` files in your vault
- **CLI** — `start`, `stop`, `status`, `push`, `pull`, `auth`, `reset`, `conflicts`
- **Web dashboard** — optional FastAPI + HTMX dashboard at `http://localhost:8765`
- **Secure** — Google credentials stored in system keyring (not in config files)

## Installation

```bash
# Install with pip
pip install obsidian-keep-sync

# Or with uv
uv pip install obsidian-keep-sync

# Install with dashboard support
pip install 'obsidian-keep-sync[dashboard]'

# Development
pip install 'obsidian-keep-sync[dev]'
```

## Quick Start

### 1. Configure

Copy `config.yaml` and edit:

```yaml
obsidian:
  vault_path: "~/Documents/MyVault"
  sync_folders: [""] # "" = whole vault
  exclude_patterns: ["_templates/**", ".obsidian/**"]
  front_matter_key: "keep_id"

keep:
  google_account: "you@gmail.com"
  sync_label: "obsidian-sync" # Keep label for synced notes
  inbox_label: "obsidian-inbox" # Keep label for new notes

sync:
  interval_seconds: 60
  conflict_strategy: "newer_wins" # newer_wins | keep_wins | obsidian_wins | duplicate
  two_way: true

logging:
  level: "INFO"
  file: "sync.log"
```

### 2. Authenticate

```bash
python main.py auth
```

You'll need a Google App Password:

1. Enable 2-Factor Authentication on your Google account
2. Visit https://myaccount.google.com/apppasswords
3. Generate an App Password for "Mail" or "Other"
4. Paste it when prompted

### 3. Run

```bash
# One-shot push (Obsidian → Keep)
python main.py push

# One-shot pull (Keep → Obsidian)
python main.py pull

# Dry run (see what would change)
python main.py push --dry-run
python main.py pull --dry-run

# Start daemon
python main.py start

# Start daemon in background (Unix)
python main.py start --daemon

# Check status
python main.py status

# Launch web dashboard
python main.py dashboard

# List conflicts
python main.py conflicts
```

## Architecture

```
obsidian-keep-sync/
├── main.py                  # CLI entry point
├── config.yaml              # User configuration
├── pyproject.toml           # Dependencies
├── sync/
│   ├── engine.py            # Orchestration (diff, merge, push)
│   ├── state.py             # SQLite sync state
│   └── conflict.py          # Conflict detection & resolution
├── adapters/
│   ├── obsidian.py          # Obsidian vault read/write
│   └── keep.py              # Google Keep API (gkeepapi)
├── converters/
│   ├── md_to_keep.py        # Markdown → Keep text
│   └── keep_to_md.py        # Keep text → Markdown
├── dashboard/               # Optional web UI
│   ├── app.py               # FastAPI app
│   └── templates/
└── tests/
    ├── test_converters.py
    └── test_engine.py
```

## How It Works

1. **State tracking** — SQLite database tracks note IDs, modification times, content hashes
2. **Polling loop** — every `interval_seconds`, sync engine:
   - Reads Obsidian vault for changed `.md` files
   - Fetches Keep notes with `sync_label`
   - Compares timestamps against stored state
   - Resolves conflicts per configured strategy
   - Updates both sides
3. **File watching** — optional watchdog integration for instant Obsidian → Keep push
4. **Inbox flow** — Keep notes with `inbox_label` but no `sync_label` become new Obsidian notes in `Inbox/`

## Tech Stack

| Layer         | Choice                          |
| ------------- | ------------------------------- |
| Language      | Python 3.11+                    |
| Keep API      | gkeepapi (unofficial)           |
| Auth          | Google App Password via keyring |
| File watching | watchdog                        |
| State store   | SQLite                          |
| Markdown      | mistletoe                       |
| Scheduling    | APScheduler                     |
| Config        | PyYAML + pydantic-settings      |
| Dashboard     | FastAPI + Jinja2 + HTMX         |

## License

MIT
