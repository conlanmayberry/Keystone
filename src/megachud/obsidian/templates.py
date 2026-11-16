from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import yaml

from megachud.models.memory_entry import MemoryEntry
from megachud.models.reflection import Reflection
from megachud.models.task import Task

if TYPE_CHECKING:  # avoids a circular import — research.py imports index.py, not this
    from megachud.obsidian.research import ResearchNote

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


def render_research_note(note: "ResearchNote", sources: list[str], task: Task | None) -> str:
    """Unlike the two renderers above, this one contributes almost no
    prose: `note.body_markdown` is written directly by the LLM and is
    passed through untouched. Everything here is the machinery Obsidian
    needs around it — frontmatter for the Properties panel and tag search,
    and a Links section listing the vault notes the body already links to
    inline, so the connections are visible without reading the whole note.

    No `# Title` heading: Obsidian titles a note by its filename, and a
    duplicated H1 shows up twice in reading view.
    """
    frontmatter = {
        "type": "research",
        "title": note.title,
        "summary": note.summary,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tags": ["research", *note.tags],
        "model": note.model,
        "task_id": task.id if task is not None else None,
        "source_urls": sources,
    }
    lines = [
        "---",
        yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip(),
        "---",
        "",
        note.body_markdown.strip(),
    ]

    if note.open_questions:
        lines += ["", "## Open questions"]
        lines += [f"- {question}" for question in note.open_questions]

    if sources:
        lines += ["", "## Sources"]
        lines += [f"- {source}" for source in sources]

    if note.linked_notes or task is not None:
        lines += ["", LINKS_MARKER]
        for linked in note.linked_notes:
            display = "" if linked.title == linked.link_target else f"|{linked.title}"
            lines.append(f"- [[{linked.link_target}{display}]]")
        if task is not None:
            lines.append(f"- Task: [[tasks/{task.id}|{task.title}]]")

    return "\n".join(lines) + "\n"
