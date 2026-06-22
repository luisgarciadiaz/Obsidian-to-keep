import hashlib
import logging
import time
from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings

from adapters.keep import KeepAdapter, KeepNote
from adapters.obsidian import ObsidianAdapter, ObsidianNote
from converters.md_to_keep import extract_title, md_to_keep_text
from sync.conflict import (
    ConflictResult,
    ConflictStrategy,
    detect_conflict,
    resolve_conflict,
)
from sync.state import SyncStateDB, SyncStateRow

log = logging.getLogger(__name__)


class ObsidianConfig(BaseModel):
    vault_path: str = "~/Documents/MyVault"
    sync_folders: list[str] = [""]
    exclude_patterns: list[str] = ["_templates/**", ".obsidian/**"]
    front_matter_key: str = "keep_id"


class KeepConfig(BaseModel):
    google_account: str = ""
    sync_label: str = "obsidian-sync"
    inbox_label: str = "obsidian-inbox"


class SyncConfig(BaseModel):
    interval_seconds: int = 60
    watch_obsidian: bool = True
    conflict_strategy: str = "newer_wins"
    two_way: bool = True


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "sync.log"


class Settings(BaseSettings):
    obsidian: ObsidianConfig = ObsidianConfig()
    keep: KeepConfig = KeepConfig()
    sync: SyncConfig = SyncConfig()
    logging: LoggingConfig = LoggingConfig()

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Settings":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        with open(p, "r") as f:
            data = yaml.safe_load(f)
        return cls(**data)


class SyncEngine:
    def __init__(self, settings: Settings, state_db: SyncStateDB):
        self.settings = settings
        self.state = state_db
        self.obsidian = ObsidianAdapter(
            vault_path=settings.obsidian.vault_path,
            front_matter_key=settings.obsidian.front_matter_key,
        )
        self.keep = KeepAdapter(email=settings.keep.google_account)
        self.strategy = ConflictStrategy(settings.sync.conflict_strategy)
        self.stats: dict = {
            "last_run": None,
            "notes_pushed": 0,
            "notes_pulled": 0,
            "conflicts": 0,
            "errors": 0,
        }

    def push_obsidian_to_keep(self, dry_run: bool = False) -> list[dict]:
        results: list[dict] = []
        notes = self.obsidian.list_notes(
            sync_folders=self.settings.obsidian.sync_folders,
            exclude_patterns=self.settings.obsidian.exclude_patterns,
        )

        for note in notes:
            result = {"file": note.file_path, "title": note.title, "action": None}
            state_row = None
            if note.keep_id:
                state_row = self.state.get(note.keep_id)
                keep_note = self.keep.get_note(note.keep_id) if not dry_run else None
                if keep_note is None and not dry_run:
                    log.warning("Keep note %s not found (may have been deleted)", note.keep_id)
                    note.keep_id = None

            if note.keep_id is None:
                if dry_run:
                    result["action"] = "create"
                    results.append(result)
                    continue
                keep_text = md_to_keep_text(note.raw_content)
                created = self.keep.create_note(
                    title=note.title or extract_title(note.body),
                    text=keep_text,
                    labels=[self.settings.keep.sync_label],
                )
                self.obsidian.set_keep_id(note.file_path, created.note_id)
                content_hash = self._content_hash(note.raw_content)
                self.state.upsert(
                    SyncStateRow(
                        note_id=created.note_id,
                        file_path=note.file_path,
                        obsidian_mtime=note.mtime,
                        keep_updated=created.updated or "",
                        content_hash=content_hash,
                        sync_direction="o2k",
                    )
                )
                result["action"] = "created"
                result["keep_id"] = created.note_id
                self.stats["notes_pushed"] += 1

            elif state_row and note.mtime > state_row.obsidian_mtime:
                if dry_run:
                    result["action"] = "update"
                    results.append(result)
                    continue
                keep_text = md_to_keep_text(note.raw_content)
                updated_title = note.title or extract_title(note.body)
                self.keep.update_note(note.keep_id, updated_title, keep_text)
                content_hash = self._content_hash(note.raw_content)
                updated_keep = self.keep.get_note(note.keep_id)
                keep_updated = updated_keep.updated if updated_keep and updated_keep.updated else ""
                self.state.upsert(
                    SyncStateRow(
                        note_id=note.keep_id,
                        file_path=note.file_path,
                        obsidian_mtime=note.mtime,
                        keep_updated=keep_updated,
                        content_hash=content_hash,
                        sync_direction="o2k",
                    )
                )
                result["action"] = "updated"
                self.stats["notes_pushed"] += 1

            results.append(result)
        return results

    def pull_keep_to_obsidian(self, dry_run: bool = False) -> list[dict]:
        results: list[dict] = []
        keep_notes = self.keep.find_notes(self.settings.keep.sync_label)

        for keep_note in keep_notes:
            result = {"keep_id": keep_note.note_id, "title": keep_note.title, "action": None}
            state_row = self.state.get(keep_note.note_id)

            if keep_note.trashed or keep_note.archived:
                if state_row:
                    self.state.delete(keep_note.note_id)
                    if not dry_run:
                        self.obsidian.delete_or_move(state_row.file_path)
                    result["action"] = "deleted"
                continue

            if state_row is None:
                if dry_run:
                    result["action"] = "create"
                    results.append(result)
                    continue

                markdown = self.keep.to_markdown(keep_note)
                title_slug = _slugify(keep_note.title or "untitled")
                rel_path = f"{title_slug}.md"
                note = ObsidianNote(
                    file_path=rel_path,
                    title=keep_note.title,
                    body=markdown,
                    keep_id=keep_note.note_id,
                )
                self.obsidian.write_note(note)
                self.obsidian.set_keep_id(rel_path, keep_note.note_id)
                content_hash = self._content_hash(markdown)
                file_mtime = (self.obsidian.vault_path / rel_path).stat().st_mtime
                self.state.upsert(
                    SyncStateRow(
                        note_id=keep_note.note_id,
                        file_path=rel_path,
                        obsidian_mtime=file_mtime,
                        keep_updated=keep_note.updated or "",
                        content_hash=content_hash,
                        sync_direction="k2o",
                    )
                )
                result["action"] = "created"
                result["file_path"] = rel_path
                self.stats["notes_pulled"] += 1

            elif self._keep_has_changed(keep_note, state_row):
                obsidian_note = self.obsidian.read_note(state_row.file_path)
                if obsidian_note is None:
                    result["action"] = "error"
                    result["error"] = f"Obsidian note not found: {state_row.file_path}"
                    continue

                if detect_conflict(state_row, obsidian_note, keep_note):
                    if dry_run:
                        result["action"] = "conflict"
                        results.append(result)
                        continue
                    resolution = resolve_conflict(
                        self.strategy, state_row, obsidian_note, keep_note
                    )
                    self._apply_resolution(resolution, state_row, keep_note)
                    result["action"] = f"conflict_resolved_{resolution.direction}"
                    self.stats["conflicts"] += 1
                else:
                    if dry_run:
                        result["action"] = "update"
                        results.append(result)
                        continue
                    markdown = self.keep.to_markdown(keep_note)
                    updated_note = ObsidianNote(
                        file_path=state_row.file_path,
                        title=keep_note.title,
                        body=markdown,
                        keep_id=keep_note.note_id,
                    )
                    self.obsidian.write_note(updated_note)
                    file_mtime = (self.obsidian.vault_path / state_row.file_path).stat().st_mtime
                    self.state.upsert(
                        SyncStateRow(
                            note_id=keep_note.note_id,
                            file_path=state_row.file_path,
                            obsidian_mtime=file_mtime,
                            keep_updated=keep_note.updated or "",
                            content_hash=self._content_hash(markdown),
                            sync_direction="k2o",
                        )
                    )
                    result["action"] = "updated"
                    self.stats["notes_pulled"] += 1

            results.append(result)

        inbox_notes = self.keep.find_inbox_notes(
            self.settings.keep.inbox_label, self.settings.keep.sync_label
        )
        for inbox_note in inbox_notes:
            if dry_run:
                results.append(
                    {
                        "keep_id": inbox_note.note_id,
                        "title": inbox_note.title,
                        "action": "create_from_inbox",
                    }
                )
                continue
            markdown = self.keep.to_markdown(inbox_note)
            title_slug = _slugify(inbox_note.title or "untitled")
            rel_path = f"Inbox/{title_slug}.md"
            note = ObsidianNote(
                file_path=rel_path,
                title=inbox_note.title,
                body=markdown,
                keep_id=inbox_note.note_id,
            )
            self.obsidian.write_note(note)
            self.obsidian.set_keep_id(rel_path, inbox_note.note_id)
            self.keep.add_label(inbox_note.note_id, self.settings.keep.sync_label)
            file_mtime = (self.obsidian.vault_path / rel_path).stat().st_mtime
            self.state.upsert(
                SyncStateRow(
                    note_id=inbox_note.note_id,
                    file_path=rel_path,
                    obsidian_mtime=file_mtime,
                    keep_updated=inbox_note.updated or "",
                    content_hash=self._content_hash(markdown),
                    sync_direction="k2o",
                )
            )
            results.append(
                {
                    "keep_id": inbox_note.note_id,
                    "title": inbox_note.title,
                    "action": "created_from_inbox",
                    "file_path": rel_path,
                }
            )
            self.stats["notes_pulled"] += 1

        return results

    def run_once(self, dry_run: bool = False):
        log.info("Starting sync cycle (dry_run=%s)", dry_run)
        push_results = self.push_obsidian_to_keep(dry_run=dry_run)
        if self.settings.sync.two_way:
            pull_results = self.pull_keep_to_obsidian(dry_run=dry_run)
        else:
            pull_results = []
        self.stats["last_run"] = datetime.now().isoformat()
        log.info(
            "Sync cycle complete: %d pushed, %d pulled, %d conflicts, %d errors",
            self.stats["notes_pushed"],
            self.stats["notes_pulled"],
            self.stats["conflicts"],
            self.stats["errors"],
        )
        return push_results, pull_results

    def _apply_resolution(
        self, resolution: ConflictResult, state_row: SyncStateRow, keep_note: KeepNote
    ):
        if resolution.direction == "o2k" and resolution.obsidian_content:
            keep_text = md_to_keep_text(resolution.obsidian_content)
            self.keep.update_note(state_row.note_id, keep_note.title, keep_text)
            self.state.upsert(
                SyncStateRow(
                    note_id=state_row.note_id,
                    file_path=state_row.file_path,
                    obsidian_mtime=time.time(),
                    keep_updated=keep_note.updated or "",
                    content_hash=self._content_hash(resolution.obsidian_content),
                    sync_direction="o2k",
                )
            )
        elif resolution.direction == "k2o" and resolution.keep_content:
            markdown = self.keep.to_markdown(keep_note)
            updated_note = ObsidianNote(
                file_path=state_row.file_path,
                title=keep_note.title,
                body=markdown,
                keep_id=keep_note.note_id,
            )
            self.obsidian.write_note(updated_note)
            file_mtime = (self.obsidian.vault_path / state_row.file_path).stat().st_mtime
            self.state.upsert(
                SyncStateRow(
                    note_id=state_row.note_id,
                    file_path=state_row.file_path,
                    obsidian_mtime=file_mtime,
                    keep_updated=keep_note.updated or "",
                    content_hash=self._content_hash(markdown),
                    sync_direction="k2o",
                )
            )

    def _keep_has_changed(self, keep_note: KeepNote, state_row: SyncStateRow) -> bool:
        if not keep_note.updated:
            return False
        cur = keep_note.updated
        return cur > state_row.keep_updated

    @staticmethod
    def _content_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _slugify(title: str) -> str:
    import re

    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug[:100].strip("-")
