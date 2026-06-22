import os
from pathlib import Path
from typing import Optional

import frontmatter

from converters.md_to_keep import extract_tags, extract_tasks, extract_title


class ObsidianNote:
    def __init__(
        self,
        file_path: str,
        title: str = "",
        body: str = "",
        tags: Optional[list[str]] = None,
        tasks: Optional[list[tuple[bool, str]]] = None,
        keep_id: Optional[str] = None,
        front_matter: Optional[dict] = None,
        mtime: float = 0.0,
    ):
        self.file_path = file_path
        self.title = title
        self.body = body
        self.tags = tags or []
        self.tasks = tasks or []
        self.keep_id = keep_id
        self.front_matter = front_matter or {}
        self.mtime = mtime

    @property
    def raw_content(self) -> str:
        post = frontmatter.Post(self.body, **self.front_matter)
        return frontmatter.dumps(post)

    def __repr__(self):
        return f"<ObsidianNote '{self.title}' @ {self.file_path}>"


class ObsidianAdapter:
    def __init__(self, vault_path: str | Path, front_matter_key: str = "keep_id"):
        self.vault_path = Path(vault_path).expanduser().resolve()
        self.front_matter_key = front_matter_key

    def list_notes(
        self,
        sync_folders: Optional[list[str]] = None,
        exclude_patterns: Optional[list[str]] = None,
    ) -> list[ObsidianNote]:
        notes: list[ObsidianNote] = []
        folders = sync_folders or [""]
        excludes = exclude_patterns or []

        for folder in folders:
            search_path = self.vault_path / folder if folder else self.vault_path
            if not search_path.exists():
                continue
            for root, _dirs, files in os.walk(search_path):
                rel_root = str(Path(root).relative_to(self.vault_path))
                if self._is_excluded(rel_root, excludes):
                    continue
                for fname in files:
                    if not fname.endswith(".md"):
                        continue
                    fpath = Path(root) / fname
                    rel_path = str(fpath.relative_to(self.vault_path))
                    if self._is_excluded(rel_path, excludes):
                        continue
                    note = self.read_note(rel_path)
                    if note:
                        notes.append(note)
        return notes

    def read_note(self, rel_path: str) -> Optional[ObsidianNote]:
        full_path = self.vault_path / rel_path
        if not full_path.exists():
            return None
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                post = frontmatter.load(f)
        except Exception:
            return None

        body = post.content
        meta = dict(post.metadata)
        title = meta.get("title", "") or extract_title(body)
        tags: list[str] = meta.get("tags", []) or extract_tags(body)
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]
        tasks = extract_tasks(body)
        keep_id = meta.get(self.front_matter_key)
        mtime = full_path.stat().st_mtime

        return ObsidianNote(
            file_path=rel_path,
            title=title,
            body=body,
            tags=tags,
            tasks=tasks,
            keep_id=str(keep_id) if keep_id is not None else None,
            front_matter=meta,
            mtime=mtime,
        )

    def write_note(self, note: ObsidianNote):
        full_path = self.vault_path / note.file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        post = frontmatter.Post(note.body, **note.front_matter)
        raw = frontmatter.dumps(post)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(raw)

    def set_keep_id(self, rel_path: str, keep_id: str):
        full_path = self.vault_path / rel_path
        if not full_path.exists():
            return
        with open(full_path, "r", encoding="utf-8") as f:
            post = frontmatter.load(f)
        post.metadata[self.front_matter_key] = keep_id
        raw = frontmatter.dumps(post)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(raw)

    def delete_or_move(self, rel_path: str, trash_folder: str = "_trash"):
        full_path = self.vault_path / rel_path
        if not full_path.exists():
            return
        trash_dir = self.vault_path / trash_folder
        trash_dir.mkdir(parents=True, exist_ok=True)
        dest = trash_dir / Path(rel_path).name
        full_path.rename(dest)

    def _is_excluded(self, path: str, patterns: list[str]) -> bool:
        for pat in patterns:
            if pat.endswith("/**"):
                base = pat[:-3]
                if path.startswith(base):
                    return True
            elif "/**" in pat:
                base = pat.split("/**")[0]
                if base in path:
                    return True
            elif fnmatch_path(path, pat):
                return True
        return False


def fnmatch_path(path: str, pattern: str) -> bool:
    import fnmatch
    if "/" in pattern or "\\" in pattern:
        return fnmatch.fnmatch(path, pattern)
    parts = path.replace("\\", "/").split("/")
    return any(fnmatch.fnmatch(p, pattern) for p in parts)
