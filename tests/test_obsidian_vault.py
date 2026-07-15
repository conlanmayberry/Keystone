from __future__ import annotations

import json
from datetime import datetime, timezone

import yaml

from megachud.models.memory_entry import MemoryEntry, MemoryType
from megachud.models.reflection import Reflection
from megachud.models.task import Task, TaskStatus
from megachud.obsidian.vault import VaultWriter

# CreatedAtMixin's default only fires on session flush; these tests build
# ORM objects standalone (no session), so created_at must be set explicitly.
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_task(**overrides):
    defaults = dict(
        id="task-1", title="Do a thing", prompt="please do the thing", status=TaskStatus.SUCCEEDED, created_at=_NOW
    )
    defaults.update(overrides)
    return Task(**defaults)


def make_entry(**overrides):
    defaults = dict(
        id="entry-1",
        memory_type=MemoryType.EPISODIC,
        title="Episode: Do a thing",
        content="did the thing successfully",
        source_task_id="task-1",
        tags_json='["episodic"]',
        importance=0.5,
        created_at=_NOW,
    )
    defaults.update(overrides)
    return MemoryEntry(**defaults)


def _parse(text):
    _, raw, body = text.split("---", 2)
    return yaml.safe_load(raw), body.strip()


def test_write_memory_entry_creates_file_with_frontmatter(tmp_vault):
    writer = VaultWriter(tmp_vault)
    task = make_task()
    entry = make_entry()

    relative_path = writer.write_memory_entry(entry, task)

    full_path = tmp_vault / relative_path
    assert full_path.exists()
    assert relative_path == full_path.relative_to(tmp_vault)

    text = full_path.read_text(encoding="utf-8")
    frontmatter, body = _parse(text)
    assert frontmatter["id"] == "entry-1"
    assert frontmatter["type"] == "episodic"
    assert frontmatter["task_id"] == "task-1"
    assert frontmatter["tags"] == ["episodic"]
    assert "did the thing successfully" in body
    assert "[[tasks/task-1|Do a thing]]" in body


def test_write_memory_entry_without_task_has_no_task_link(tmp_vault):
    writer = VaultWriter(tmp_vault)
    entry = make_entry(id="entry-2", memory_type=MemoryType.USER, source_task_id=None)

    relative_path = writer.write_memory_entry(entry, None)
    text = (tmp_vault / relative_path).read_text(encoding="utf-8")

    assert "## Links" not in text


def test_write_memory_entry_is_idempotent(tmp_vault):
    writer = VaultWriter(tmp_vault)
    entry = make_entry()
    writer.write_memory_entry(entry, None)

    entry.content = "updated content"
    relative_path = writer.write_memory_entry(entry, None)

    text = (tmp_vault / relative_path).read_text(encoding="utf-8")
    assert "updated content" in text
    assert "did the thing successfully" not in text


def test_write_task_note_links_to_memory_entries(tmp_vault):
    writer = VaultWriter(tmp_vault)
    task = make_task()
    reflection = Reflection(
        task_id="task-1",
        what_worked='["it worked"]',
        what_failed="[]",
        wrong_assumptions="[]",
        should_change='["no change indicated"]',
        become_long_term_knowledge=False,
    )
    entry = make_entry()

    relative_path = writer.write_task_note(task, reflection, [entry])
    text = (tmp_vault / relative_path).read_text(encoding="utf-8")

    frontmatter, body = _parse(text)
    assert frontmatter["id"] == "task-1"
    assert frontmatter["type"] == "task"
    assert frontmatter["status"] == "succeeded"
    assert "it worked" in body
    assert "[[episodic/entry-1]]" in body
