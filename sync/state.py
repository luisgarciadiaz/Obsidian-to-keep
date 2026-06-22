import hashlib
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class SyncStateRow:
    note_id: str
    file_path: str
    obsidian_mtime: float = 0.0
    keep_updated: str = ""
    content_hash: str = ""
    sync_direction: str = ""
    conflict: bool = False


class SyncStateDB:
    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)
        self._local = threading.local()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
        return self._local.conn

    def initialize(self):
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_state (
                note_id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                obsidian_mtime REAL NOT NULL DEFAULT 0,
                keep_updated TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL DEFAULT '',
                sync_direction TEXT NOT NULL DEFAULT '',
                conflict INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._conn.commit()

    def get(self, note_id: str) -> Optional[SyncStateRow]:
        row = self._conn.execute(
            "SELECT * FROM sync_state WHERE note_id = ?", (note_id,)
        ).fetchone()
        if row is None:
            return None
        return SyncStateRow(
            note_id=row["note_id"],
            file_path=row["file_path"],
            obsidian_mtime=row["obsidian_mtime"],
            keep_updated=row["keep_updated"],
            content_hash=row["content_hash"],
            sync_direction=row["sync_direction"],
            conflict=bool(row["conflict"]),
        )

    def get_by_path(self, file_path: str) -> Optional[SyncStateRow]:
        row = self._conn.execute(
            "SELECT * FROM sync_state WHERE file_path = ?", (file_path,)
        ).fetchone()
        if row is None:
            return None
        return SyncStateRow(
            note_id=row["note_id"],
            file_path=row["file_path"],
            obsidian_mtime=row["obsidian_mtime"],
            keep_updated=row["keep_updated"],
            content_hash=row["content_hash"],
            sync_direction=row["sync_direction"],
            conflict=bool(row["conflict"]),
        )

    def upsert(self, row: SyncStateRow):
        self._conn.execute(
            """
            INSERT INTO sync_state
                (note_id, file_path, obsidian_mtime, keep_updated,
                 content_hash, sync_direction, conflict)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(note_id) DO UPDATE SET
                file_path = excluded.file_path,
                obsidian_mtime = excluded.obsidian_mtime,
                keep_updated = excluded.keep_updated,
                content_hash = excluded.content_hash,
                sync_direction = excluded.sync_direction,
                conflict = excluded.conflict
            """,
            (
                row.note_id,
                row.file_path,
                row.obsidian_mtime,
                row.keep_updated,
                row.content_hash,
                row.sync_direction,
                1 if row.conflict else 0,
            ),
        )
        self._conn.commit()

    def delete(self, note_id: str):
        self._conn.execute("DELETE FROM sync_state WHERE note_id = ?", (note_id,))
        self._conn.commit()

    def all(self) -> list[SyncStateRow]:
        rows = self._conn.execute("SELECT * FROM sync_state").fetchall()
        return [
            SyncStateRow(
                note_id=r["note_id"],
                file_path=r["file_path"],
                obsidian_mtime=r["obsidian_mtime"],
                keep_updated=r["keep_updated"],
                content_hash=r["content_hash"],
                sync_direction=r["sync_direction"],
                conflict=bool(r["conflict"]),
            )
            for r in rows
        ]

    def conflicts(self) -> list[SyncStateRow]:
        rows = self._conn.execute("SELECT * FROM sync_state WHERE conflict = 1").fetchall()
        return [
            SyncStateRow(
                note_id=r["note_id"],
                file_path=r["file_path"],
                obsidian_mtime=r["obsidian_mtime"],
                keep_updated=r["keep_updated"],
                content_hash=r["content_hash"],
                sync_direction=r["sync_direction"],
                conflict=bool(r["conflict"]),
            )
            for r in rows
        ]

    def clear(self):
        self._conn.execute("DELETE FROM sync_state")
        self._conn.commit()

    @staticmethod
    def compute_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
