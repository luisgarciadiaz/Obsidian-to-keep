import logging
from datetime import datetime
from enum import Enum
from typing import Optional

from adapters.keep import KeepNote
from adapters.obsidian import ObsidianNote
from sync.state import SyncStateRow

log = logging.getLogger(__name__)


class ConflictStrategy(str, Enum):
    NEWER_WINS = "newer_wins"
    KEEP_WINS = "keep_wins"
    OBSIDIAN_WINS = "obsidian_wins"
    DUPLICATE = "duplicate"


class ConflictResult:
    def __init__(
        self,
        direction: str,
        note_id: str,
        resolved: bool,
        keep_content: Optional[str] = None,
        obsidian_content: Optional[str] = None,
        conflict_md_path: Optional[str] = None,
    ):
        self.direction = direction
        self.note_id = note_id
        self.resolved = resolved
        self.keep_content = keep_content
        self.obsidian_content = obsidian_content
        self.conflict_md_path = conflict_md_path


def detect_conflict(
    state: SyncStateRow,
    obsidian_note: ObsidianNote,
    keep_note: KeepNote,
) -> bool:
    obsidian_changed = obsidian_note.mtime > state.obsidian_mtime
    keep_changed = _keep_is_newer(keep_note, state.keep_updated)
    return obsidian_changed and keep_changed


def resolve_conflict(
    strategy: ConflictStrategy,
    state: SyncStateRow,
    obsidian_note: ObsidianNote,
    keep_note: KeepNote,
) -> ConflictResult:
    log.info(
        "Resolving conflict for %s (strategy=%s)", state.note_id, strategy.value
    )

    if strategy == ConflictStrategy.KEEP_WINS:
        return ConflictResult(
            direction="k2o",
            note_id=state.note_id,
            resolved=True,
            keep_content=keep_note.text,
        )

    if strategy == ConflictStrategy.OBSIDIAN_WINS:
        return ConflictResult(
            direction="o2k",
            note_id=state.note_id,
            resolved=True,
            obsidian_content=obsidian_note.raw_content,
        )

    if strategy == ConflictStrategy.DUPLICATE:
        conflict_path = _make_conflict_path(obsidian_note.file_path)
        return ConflictResult(
            direction="",
            note_id=state.note_id,
            resolved=False,
            keep_content=keep_note.text,
            obsidian_content=obsidian_note.raw_content,
            conflict_md_path=conflict_path,
        )

    obsidian_mtime = obsidian_note.mtime
    keep_updated = _parse_keep_timestamp(keep_note.updated) if keep_note.updated else 0.0

    if obsidian_mtime >= keep_updated:
        return ConflictResult(
            direction="o2k",
            note_id=state.note_id,
            resolved=True,
            obsidian_content=obsidian_note.raw_content,
        )
    else:
        return ConflictResult(
            direction="k2o",
            note_id=state.note_id,
            resolved=True,
            keep_content=keep_note.text,
        )


def _keep_is_newer(keep_note: KeepNote, last_known_updated: str) -> bool:
    if not keep_note.updated:
        return False
    cur = _parse_keep_timestamp(keep_note.updated)
    last = _parse_keep_timestamp(last_known_updated) if last_known_updated else 0.0
    return cur > last


def _parse_keep_timestamp(iso_str: str) -> float:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0.0


def _make_conflict_path(original_path: str) -> str:
    if original_path.endswith(".md"):
        return original_path[:-3] + ".conflict.md"
    return original_path + ".conflict.md"
