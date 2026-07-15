from __future__ import annotations

from megachud.memory.store import MemoryStore
from megachud.models.memory_entry import MemoryEntry, MemoryType
from megachud.obsidian.reindex import reindex_vault
from megachud.obsidian.vault import VaultWriter

VECTOR_DIM = 64


def test_reindex_inserts_new_entry_authored_directly_in_vault(session_factory, tmp_vault):
    note = tmp_vault / "user" / "hand-written.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\n"
        "id: hand-written\n"
        "type: user\n"
        "task_id: null\n"
        "created_at: '2026-01-01T00:00:00+00:00'\n"
        "tags: [manual]\n"
        "importance: 0.5\n"
        "---\n\n"
        "# A note I wrote in Obsidian\n\n"
        "remember that I prefer tabs over spaces\n",
        encoding="utf-8",
    )

    report = reindex_vault(tmp_vault, session_factory, VECTOR_DIM)

    assert report.created == 1
    assert report.updated == 0

    session = session_factory()
    try:
        entry = session.get(MemoryEntry, "hand-written")
        assert entry is not None
        assert entry.memory_type == MemoryType.USER
        assert entry.title == "A note I wrote in Obsidian"
        assert "prefer tabs over spaces" in entry.content
    finally:
        session.close()


def test_reindex_updates_existing_entry_when_note_edited_by_human(session_factory, tmp_vault):
    store = MemoryStore(session_factory, vector_dim=VECTOR_DIM)
    entry = store.create_user_entry(content="original content", title="original title")

    writer = VaultWriter(tmp_vault)
    relative_path = writer.write_memory_entry(entry, None)

    # Simulate a human editing the note directly in Obsidian.
    full_path = tmp_vault / relative_path
    edited = full_path.read_text(encoding="utf-8").replace("original content", "edited by a human in obsidian")
    edited = edited.replace("# original title", "# edited title")
    full_path.write_text(edited, encoding="utf-8")

    report = reindex_vault(tmp_vault, session_factory, VECTOR_DIM)

    assert report.updated == 1
    assert report.created == 0

    updated = store.get(entry.id)
    assert updated.content == "edited by a human in obsidian"
    assert updated.title == "edited title"


def test_reindex_skips_task_notes(session_factory, tmp_vault):
    task_note = tmp_vault / "tasks" / "task-1.md"
    task_note.parent.mkdir(parents=True, exist_ok=True)
    task_note.write_text(
        "---\nid: task-1\ntype: task\nstatus: succeeded\ncreated_at: '2026-01-01T00:00:00+00:00'\n---\n\n# A task\n\nprompt text\n",
        encoding="utf-8",
    )

    report = reindex_vault(tmp_vault, session_factory, VECTOR_DIM)

    assert report.created == 0
    assert report.updated == 0

    session = session_factory()
    try:
        assert session.get(MemoryEntry, "task-1") is None
    finally:
        session.close()


def test_reindex_report_is_empty_when_vault_has_no_memory_notes(session_factory, tmp_vault):
    report = reindex_vault(tmp_vault, session_factory, VECTOR_DIM)
    assert report.created == 0
    assert report.updated == 0
    assert report.skipped == 0
    assert report.errors == []
