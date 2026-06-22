import tempfile
from pathlib import Path

import pytest
import yaml

from sync.engine import Settings, SyncEngine
from sync.state import SyncStateDB


@pytest.fixture
def temp_vault(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    inbox = vault / "Inbox"
    inbox.mkdir()
    return vault


@pytest.fixture
def temp_config(temp_vault):
    config = {
        "obsidian": {
            "vault_path": str(temp_vault),
            "sync_folders": [""],
            "exclude_patterns": [],
            "front_matter_key": "keep_id",
        },
        "keep": {
            "google_account": "test@example.com",
            "sync_label": "obsidian-sync",
            "inbox_label": "obsidian-inbox",
        },
        "sync": {
            "interval_seconds": 60,
            "watch_obsidian": False,
            "conflict_strategy": "newer_wins",
            "two_way": True,
        },
        "logging": {
            "level": "DEBUG",
            "file": "",
        },
    }
    config_path = temp_vault.parent / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)
    return config_path


@pytest.fixture
def state_db(tmp_path):
    db = SyncStateDB(tmp_path / "test_state.db")
    db.initialize()
    return db


@pytest.fixture
def engine(temp_config, state_db):
    settings = Settings.from_yaml(temp_config)
    return SyncEngine(settings, state_db)


class TestSettings:
    def test_from_yaml(self, temp_config):
        settings = Settings.from_yaml(temp_config)
        assert settings.obsidian.vault_path.endswith("vault")
        assert settings.keep.google_account == "test@example.com"
        assert settings.sync.conflict_strategy == "newer_wins"

    def test_defaults(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(
                {"obsidian": {"vault_path": "/tmp"}, "keep": {"google_account": "x@y.com"}}, f
            )
            f.flush()
            f.close()
            settings = Settings.from_yaml(f.name)
            assert settings.sync.interval_seconds == 60
            assert settings.sync.two_way is True
            Path(f.name).unlink()

    def test_missing_config(self):
        with pytest.raises(FileNotFoundError):
            Settings.from_yaml("/nonexistent/config.yaml")


class TestSyncState:
    def test_insert_and_retrieve(self, state_db):
        from sync.state import SyncStateRow

        row = SyncStateRow(
            note_id="test123",
            file_path="notes/test.md",
            obsidian_mtime=1000.0,
            keep_updated="2024-01-01T00:00:00",
            content_hash="abc123",
            sync_direction="o2k",
        )
        state_db.upsert(row)
        retrieved = state_db.get("test123")
        assert retrieved is not None
        assert retrieved.file_path == "notes/test.md"
        assert retrieved.obsidian_mtime == 1000.0

    def test_get_by_path(self, state_db):
        from sync.state import SyncStateRow

        state_db.upsert(SyncStateRow(note_id="id1", file_path="a.md"))
        state_db.upsert(SyncStateRow(note_id="id2", file_path="b.md"))

        found = state_db.get_by_path("b.md")
        assert found is not None
        assert found.note_id == "id2"

    def test_delete(self, state_db):
        from sync.state import SyncStateRow

        state_db.upsert(SyncStateRow(note_id="delme", file_path="del.md"))
        state_db.delete("delme")
        assert state_db.get("delme") is None

    def test_all_and_conflicts(self, state_db):
        from sync.state import SyncStateRow

        state_db.upsert(SyncStateRow(note_id="a", file_path="a.md", conflict=False))
        state_db.upsert(SyncStateRow(note_id="b", file_path="b.md", conflict=True))

        assert len(state_db.all()) == 2
        assert len(state_db.conflicts()) == 1
        assert state_db.conflicts()[0].note_id == "b"

    def test_clear(self, state_db):
        from sync.state import SyncStateRow

        state_db.upsert(SyncStateRow(note_id="a", file_path="a.md"))
        state_db.upsert(SyncStateRow(note_id="b", file_path="b.md"))
        state_db.clear()
        assert len(state_db.all()) == 0

    def test_compute_hash(self):
        h = SyncStateDB.compute_hash("hello")
        assert len(h) == 64
        assert h == SyncStateDB.compute_hash("hello")
        assert h != SyncStateDB.compute_hash("world")

    def test_content_hash(self, engine):
        h = engine._content_hash("test content")
        assert len(h) == 64


class TestConflict:
    def test_strategy_values(self):
        from sync.conflict import ConflictStrategy

        assert ConflictStrategy.NEWER_WINS.value == "newer_wins"
        assert ConflictStrategy.KEEP_WINS.value == "keep_wins"
        assert ConflictStrategy.OBSIDIAN_WINS.value == "obsidian_wins"
        assert ConflictStrategy.DUPLICATE.value == "duplicate"

    def test_detect_conflict_both_changed(self, state_db):
        from adapters.keep import KeepNote
        from adapters.obsidian import ObsidianNote
        from sync.conflict import detect_conflict
        from sync.state import SyncStateRow

        state = SyncStateRow(
            note_id="n1",
            file_path="test.md",
            obsidian_mtime=100.0,
            keep_updated="2024-01-01T00:00:00",
        )
        obsidian = ObsidianNote(file_path="test.md", mtime=200.0)
        keep = KeepNote(note_id="n1", updated="2024-02-01T00:00:00")

        assert detect_conflict(state, obsidian, keep)

    def test_detect_conflict_no_conflict(self, state_db):
        from adapters.keep import KeepNote
        from adapters.obsidian import ObsidianNote
        from sync.conflict import detect_conflict
        from sync.state import SyncStateRow

        state = SyncStateRow(
            note_id="n1",
            file_path="test.md",
            obsidian_mtime=100.0,
            keep_updated="2024-02-01T00:00:00",
        )
        obsidian = ObsidianNote(file_path="test.md", mtime=100.0)
        keep = KeepNote(note_id="n1", updated="2024-01-01T00:00:00")

        assert not detect_conflict(state, obsidian, keep)


class TestSlugify:
    def test_basic_slug(self):
        from sync.engine import _slugify

        assert _slugify("Hello World") == "hello-world"
        assert _slugify("My Note!") == "my-note"
        assert _slugify("  Spaces  ") == "spaces"
