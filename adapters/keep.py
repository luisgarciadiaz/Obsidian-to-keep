import logging
import os
import time
from typing import Optional

import gkeepapi
import keyring

from converters.keep_to_md import keep_to_md

log = logging.getLogger(__name__)

SERVICE_NAME = "obsidian-keep-sync"


class KeepNote:
    def __init__(
        self,
        note_id: str,
        title: str = "",
        text: str = "",
        labels: Optional[list[str]] = None,
        color: int = 0,
        pinned: bool = False,
        trashed: bool = False,
        archived: bool = False,
        updated: Optional[str] = None,
    ):
        self.note_id = note_id
        self.title = title
        self.text = text
        self.labels = labels or []
        self.color = color
        self.pinned = pinned
        self.trashed = trashed
        self.archived = archived
        self.updated = updated

    def __repr__(self):
        return f"<KeepNote '{self.title}' ({self.note_id})>"


class KeepAdapter:
    def __init__(self, email: str, master_token: Optional[str] = None):
        self.email = email
        self._master_token = master_token
        self._keep: Optional[gkeepapi.Keep] = None

    def _get_master_token(self) -> str:
        if self._master_token:
            return self._master_token
        stored = keyring.get_password(SERVICE_NAME, self.email)
        if stored:
            return stored
        raise RuntimeError(
            f"No master token found for {self.email}. "
            "Run `python main.py auth` first."
        )

    def _store_master_token(self, token: str):
        keyring.set_password(SERVICE_NAME, self.email, token)

    def authenticate(self, master_token: str):
        self._keep = gkeepapi.Keep()
        self._keep.authenticate(self.email, master_token)
        self._store_master_token(master_token)
        log.info("Authenticated with Google Keep as %s", self.email)

    def authenticate_device_flow(self, token: str):
        self._keep = gkeepapi.Keep()
        self._keep.authenticate(self.email, token)
        self._store_master_token(token)
        log.info("Authenticated with Google Keep (device flow) as %s", self.email)

    def resume(self):
        token = self._get_master_token()
        self._keep = gkeepapi.Keep()
        self._keep.authenticate(self.email, token)
        log.info("Resumed authenticated session for %s", self.email)

    def sync(self):
        if self._keep is None:
            self.resume()
        try:
            self._keep.sync()
        except gkeepapi.exception.LoginException:
            log.warning("Session expired, re-authenticating...")
            self.resume()
            self._keep.sync()

    @property
    def keep(self) -> gkeepapi.Keep:
        if self._keep is None:
            self.resume()
        return self._keep

    def find_notes(self, label_name: str) -> list[KeepNote]:
        self.sync()
        label = self._find_or_create_label(label_name)
        results: list[KeepNote] = []
        for gnote in self.keep.find(labels=[label]):
            results.append(self._gkeep_to_keepnote(gnote))
        return results

    def find_inbox_notes(self, inbox_label: str, sync_label: str) -> list[KeepNote]:
        self.sync()
        inbox = self._find_or_create_label(inbox_label)
        sync = self._find_or_create_label(sync_label)
        results: list[KeepNote] = []
        for gnote in self.keep.find(labels=[inbox]):
            has_sync = any(l for l in gnote.labels.all() if l == sync)
            if not has_sync:
                results.append(self._gkeep_to_keepnote(gnote))
        return results

    def get_note(self, note_id: str) -> Optional[KeepNote]:
        self.sync()
        try:
            gnote = self.keep.get(note_id)
            if gnote:
                return self._gkeep_to_keepnote(gnote)
        except Exception:
            return None
        return None

    def create_note(
        self,
        title: str,
        text: str,
        labels: Optional[list[str]] = None,
        pinned: bool = False,
        color: int = 0,
    ) -> KeepNote:
        self.sync()
        gnote = self.keep.createNote(title, text)
        gnote.pinned = pinned
        gnote.color = color
        if labels:
            for lbl in labels:
                label = self._find_or_create_label(lbl)
                gnote.labels.add(label)
        self.keep.sync()
        return self._gkeep_to_keepnote(gnote)

    def update_note(self, note_id: str, title: str, text: str):
        self.sync()
        gnote = self.keep.get(note_id)
        if gnote is None:
            raise ValueError(f"Note {note_id} not found")
        gnote.title = title
        gnote.text = text
        self.keep.sync()

    def add_label(self, note_id: str, label_name: str):
        self.sync()
        gnote = self.keep.get(note_id)
        if gnote is None:
            return
        label = self._find_or_create_label(label_name)
        gnote.labels.add(label)
        self.keep.sync()

    def remove_label(self, note_id: str, label_name: str):
        self.sync()
        gnote = self.keep.get(note_id)
        if gnote is None:
            return
        label = self._find_or_create_label(label_name)
        if label:
            gnote.labels.remove(label)
        self.keep.sync()

    def archive_note(self, note_id: str):
        self.sync()
        gnote = self.keep.get(note_id)
        if gnote is None:
            return
        gnote.archived = True
        self.keep.sync()

    def trash_note(self, note_id: str):
        self.sync()
        gnote = self.keep.get(note_id)
        if gnote is None:
            return
        gnote.trash = True
        self.keep.sync()

    def _find_or_create_label(self, name: str) -> gkeepapi.node.Label:
        label = self.keep.findLabel(name)
        if label is None:
            label = self.keep.createLabel(name)
        return label

    def _gkeep_to_keepnote(self, gnote) -> KeepNote:
        labels = [l.name for l in gnote.labels.all()]
        updated_iso = ""
        if gnode.timestamps.updated:
            updated_iso = (
                gnode.timestamps.updated.isoformat()
                if hasattr(gnode.timestamps.updated, "isoformat")
                else str(gnode.timestamps.updated)
            )
        return KeepNote(
            note_id=gnode.id,
            title=gnode.title,
            text=gnode.text,
            labels=labels,
            color=gnode.color,
            pinned=gnode.pinned,
            trashed=gnode.trash,
            archived=gnode.archived,
            updated=updated_iso,
        )

    def to_markdown(self, note: KeepNote) -> str:
        return keep_to_md(title=note.title, text=note.text, tags=None)

    def from_markdown(self, markdown: str) -> tuple[str, str]:
        title = ""
        text_lines: list[str] = []
        lines = markdown.split("\n")
        in_front = False
        front_done = False
        for line in lines:
            if line.startswith("---"):
                if not in_front:
                    in_front = True
                else:
                    in_front = False
                    front_done = True
                continue
            if in_front:
                continue
            if not title and line.startswith("# "):
                title = line[2:].strip()
                continue
            text_lines.append(line)
        return title, "\n".join(text_lines).strip()

    def get_updated_timestamp(self, note_id: str) -> Optional[str]:
        note = self.get_note(note_id)
        if note:
            return note.updated
        return None
