#!/usr/bin/env python3
"""
obsidian-keep-sync — bidirectional sync between Google Keep and Obsidian.

Usage:
    python main.py start          Start the sync daemon
    python main.py stop           Stop the daemon
    python main.py status         Show sync stats
    python main.py push           One-shot push all Obsidian → Keep
    python main.py pull           One-shot pull all Keep → Obsidian
    python main.py auth           Authenticate with Google
    python main.py reset          Clear sync state
    python main.py conflicts      List conflicts
    python main.py dashboard      Launch web dashboard
"""

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

from sync.engine import Settings, SyncEngine
from sync.state import SyncStateDB

log = logging.getLogger("obsidian-keep-sync")

PID_FILE = Path.home() / ".obsidian-keep-sync" / "daemon.pid"


def setup_logging(level: str = "INFO", log_file: Optional[str] = None):
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def load_settings(config_path: str = "config.yaml") -> Settings:
    try:
        return Settings.from_yaml(config_path)
    except FileNotFoundError:
        log.error("Config file not found: %s", config_path)
        log.info("Create a config.yaml or use --config PATH")
        sys.exit(1)
    except Exception as e:
        log.error("Failed to load config: %s", e)
        sys.exit(1)


def cmd_auth(args):
    settings = load_settings(args.config)
    from adapters.keep import KeepAdapter

    print("Google Keep Authentication")
    print("=" * 40)
    print(f"Account: {settings.keep.google_account}")
    print()
    print("To obtain a Google Master Token for gkeepapi:")
    print("1. Visit https://accounts.google.com/DisplayUnlockCaptcha")
    print("2. Enable 'Allow less secure apps' (or use App Password)")
    print("3. Generate an App Password at https://myaccount.google.com/apppasswords")
    print()
    token = input("Paste your Master Token / App Password: ").strip()
    if not token:
        print("No token provided. Aborting.")
        sys.exit(1)

    adapter = KeepAdapter(email=settings.keep.google_account)
    try:
        adapter.authenticate(master_token=token)
        print("Authentication successful! Token stored in system keyring.")
    except Exception as e:
        log.error("Authentication failed: %s", e)
        sys.exit(1)


def cmd_start(args):
    settings = load_settings(args.config)
    setup_logging(settings.logging.level, settings.logging.file)

    state_db = SyncStateDB(Path.home() / ".obsidian-keep-sync" / "state.db")
    state_db.initialize()

    engine = SyncEngine(settings, state_db)

    if args.daemon:
        _daemonize()

    log.info("Sync daemon started (interval=%ds)", settings.sync.interval_seconds)
    _write_pid()

    try:
        while True:
            try:
                engine.run_once()
            except Exception as e:
                log.error("Sync cycle failed: %s", e, exc_info=True)
                engine.stats["errors"] += 1
            time.sleep(settings.sync.interval_seconds)
    except KeyboardInterrupt:
        log.info("Shutdown requested")
    finally:
        _remove_pid()


def cmd_stop(args):
    if not PID_FILE.exists():
        print("Daemon is not running.")
        return
    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to daemon (PID {pid})")
        PID_FILE.unlink(missing_ok=True)
    except ProcessLookupError:
        print(f"Process {pid} not found. Removing stale PID file.")
        PID_FILE.unlink(missing_ok=True)


def cmd_status(args):
    settings = load_settings(args.config)
    state_db = SyncStateDB(Path.home() / ".obsidian-keep-sync" / "state.db")
    state_db.initialize()

    all_notes = state_db.all()
    conflicts = state_db.conflicts()

    print("Sync Status")
    print("=" * 40)
    print(f"Total synced notes: {len(all_notes)}")
    print(f"Conflicts:          {len(conflicts)}")
    print(f"Config file:        {args.config}")
    print(f"Vault path:         {settings.obsidian.vault_path}")
    print(f"Keep account:       {settings.keep.google_account}")
    print(f"Sync interval:      {settings.sync.interval_seconds}s")
    print(f"Two-way sync:       {settings.sync.two_way}")
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        print(f"Daemon:             Running (PID {pid})")
    else:
        print("Daemon:             Not running")

    if conflicts:
        print()
        print("Conflicts:")
        for c in conflicts:
            print(f"  - {c.file_path} (Keep: {c.note_id})")


def cmd_push(args):
    settings = load_settings(args.config)
    setup_logging(settings.logging.level, settings.logging.file)

    state_db = SyncStateDB(Path.home() / ".obsidian-keep-sync" / "state.db")
    state_db.initialize()

    from adapters.keep import KeepAdapter

    keep = KeepAdapter(email=settings.keep.google_account)
    keep.resume()

    engine = SyncEngine(settings, state_db)
    results = engine.push_obsidian_to_keep(dry_run=args.dry_run)

    if args.dry_run:
        print(f"DRY RUN — {len(results)} notes evaluated")
    else:
        print(f"Pushed {len(results)} notes")

    for r in results:
        action = r.get("action") or "unchanged"
        title = r.get("title", "")
        print(f"  [{action:>8}] {title}")


def cmd_pull(args):
    settings = load_settings(args.config)
    setup_logging(settings.logging.level, settings.logging.file)

    state_db = SyncStateDB(Path.home() / ".obsidian-keep-sync" / "state.db")
    state_db.initialize()

    from adapters.keep import KeepAdapter

    keep = KeepAdapter(email=settings.keep.google_account)
    keep.resume()

    engine = SyncEngine(settings, state_db)
    results = engine.pull_keep_to_obsidian(dry_run=args.dry_run)

    if args.dry_run:
        print(f"DRY RUN — {len(results)} notes evaluated")
    else:
        print(f"Pulled {len(results)} notes")

    for r in results:
        action = r.get("action") or "unchanged"
        title = r.get("title", "")
        print(f"  [{action:>8}] {title}")


def cmd_reset(args):
    if args.force:
        confirm = "yes"
    else:
        confirm = input("This will clear all sync state. Continue? [y/N]: ").strip().lower()
    if confirm not in ("y", "yes"):
        print("Aborted.")
        return

    state_db = SyncStateDB(Path.home() / ".obsidian-keep-sync" / "state.db")
    state_db.initialize()
    state_db.clear()
    print("Sync state cleared.")


def cmd_conflicts(args):
    state_db = SyncStateDB(Path.home() / ".obsidian-keep-sync" / "state.db")
    state_db.initialize()
    conflicts = state_db.conflicts()

    if not conflicts:
        print("No conflicts.")
        return

    print(f"Found {len(conflicts)} conflict(s):")
    for i, c in enumerate(conflicts, 1):
        print(f"  {i}. {c.file_path} (Keep: {c.note_id})")
        print(f"     Last sync: {c.sync_direction}, Keep updated: {c.keep_updated}")


def cmd_dashboard(args):
    try:
        from dashboard.app import run_dashboard
    except ImportError:
        print("Dashboard dependencies not installed.")
        print("Install with: pip install 'obsidian-keep-sync[dashboard]'")
        sys.exit(1)

    settings = load_settings(args.config)
    state_db = SyncStateDB(Path.home() / ".obsidian-keep-sync" / "state.db")
    state_db.initialize()

    engine = SyncEngine(settings, state_db)
    run_dashboard(engine, state_db, host=args.host, port=args.port)


def _daemonize():
    if os.name == "posix":
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
        os.setsid()
        sys.stdout.flush()
        sys.stderr.flush()
        with open(os.devnull, "w") as devnull:
            os.dup2(devnull.fileno(), sys.stdout.fileno())
            os.dup2(devnull.fileno(), sys.stderr.fileno())
    else:
        log.warning("Daemon mode not fully supported on Windows; running in foreground")


def _write_pid():
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))


def _remove_pid():
    PID_FILE.unlink(missing_ok=True)


def _validate_config(args):
    try:
        Settings.from_yaml(args.config)
        print(f"Config validates OK: {args.config}")
    except Exception as e:
        print(f"Config validation FAILED: {e}")
        sys.exit(1)


def cli():
    parser = argparse.ArgumentParser(
        description="Bidirectional sync between Google Keep and Obsidian"
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without applying")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="Authenticate with Google")

    p_start = sub.add_parser("start", help="Start sync daemon")
    p_start.add_argument("--daemon", action="store_true", help="Run as daemon (Unix)")

    sub.add_parser("stop", help="Stop sync daemon")
    sub.add_parser("status", help="Show sync status")

    sub.add_parser("push", help="Push Obsidian → Keep")
    sub.add_parser("pull", help="Pull Keep → Obsidian")

    p_reset = sub.add_parser("reset", help="Clear sync state")
    p_reset.add_argument("--force", action="store_true", help="Skip confirmation")

    sub.add_parser("conflicts", help="List sync conflicts")

    p_dash = sub.add_parser("dashboard", help="Launch web dashboard")
    p_dash.add_argument("--host", default="127.0.0.1", help="Dashboard host")
    p_dash.add_argument("--port", type=int, default=8765, help="Dashboard port")

    args = parser.parse_args()

    if hasattr(args, "verbose") and args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    commands = {
        "auth": cmd_auth,
        "start": cmd_start,
        "stop": cmd_stop,
        "status": cmd_status,
        "push": cmd_push,
        "pull": cmd_pull,
        "reset": cmd_reset,
        "conflicts": cmd_conflicts,
        "dashboard": cmd_dashboard,
    }

    cmd = commands.get(args.command)
    if cmd:
        cmd(args)


if __name__ == "__main__":
    cli()
