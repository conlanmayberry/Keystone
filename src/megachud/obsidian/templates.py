from __future__ import annotations

import json

import yaml

from megachud.models.memory_entry import MemoryEntry
from megachud.models.reflection import Reflection
from megachud.models.task import Task

LINKS_MARKER = "## Links"


def render_memory_entry(entry: MemoryEntry, task: Task | None) -> str:
    """Frontmatter (id/type/tags/importance/...) is what makes Obsidian's
    Properties panel and tag search useful with no plugin. The `[[Task
    wikilink]]` is what makes the vault's graph view/backlinks useful.
    """
    frontmatter = {
        "id": entry.id,
        "type": entry.memory_type.value,
        "task_id": entry.source_task_id,
        "created_at": entry.created_at.isoformat(),
        "tags": json.loads(entry.tags_json),
        "importance": entry.importance,
    }
    lines = [
        "---",
        yaml.safe_dump(frontmatter, sort_keys=False).strip(),
        "---",
        "",
        f"# {entry.title}",
        "",
        entry.content,
    ]

    if task is not None:
        lines += ["", LINKS_MARKER, f"- Task: [[tasks/{task.id}|{task.title}]]"]

    return "\n".join(lines) + "\n"


def render_task_note(task: Task, reflection: Reflection | None, memory_entries: list[MemoryEntry]) -> str:
    frontmatter = {
        "id": task.id,
        "type": "task",
        "status": task.status.value,
        "created_at": task.created_at.isoformat(),
    }
    lines = [
        "---",
        yaml.safe_dump(frontmatter, sort_keys=False).strip(),
        "---",
        "",
        f"# {task.title}",
        "",
        task.prompt,
    ]

    if reflection is not None:
        lines += ["", "## Reflection"]
        for label, field_value in (
            ("What worked", reflection.what_worked),
            ("What failed", reflection.what_failed),
            ("Wrong assumptions", reflection.wrong_assumptions),
            ("Should change", reflection.should_change),
        ):
            items = json.loads(field_value)
            if items:
                lines.append(f"\n**{label}:**")
                lines += [f"- {item}" for item in items]

    if memory_entries:
        lines += ["", LINKS_MARKER]
        for entry in memory_entries:
            lines.append(f"- {entry.memory_type.value.capitalize()} memory: [[{entry.memory_type.value}/{entry.id}]]")

    return "\n".join(lines) + "\n"
