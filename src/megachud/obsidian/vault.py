from __future__ import annotations

from pathlib import Path

from megachud.models.memory_entry import MemoryEntry
from megachud.models.reflection import Reflection
from megachud.models.task import Task
from megachud.obsidian import templates


class VaultWriter:
    def __init__(self, vault_root: Path) -> None:
        self._vault_root = vault_root

    def write_memory_entry(self, entry: MemoryEntry, task: Task | None) -> Path:
        """Writes vault/{type}/{id}.md (idempotent — overwrites on rewrite).
        Returns the path relative to vault_root, suitable for
        MemoryStore.set_vault_path().
        """
        relative = Path(entry.memory_type.value) / f"{entry.id}.md"
        self._write(relative, templates.render_memory_entry(entry, task))
        return relative

    def write_task_note(self, task: Task, reflection: Reflection | None, memory_entries: list[MemoryEntry]) -> Path:
        relative = Path("tasks") / f"{task.id}.md"
        self._write(relative, templates.render_task_note(task, reflection, memory_entries))
        return relative

    def _write(self, relative_path: Path, content: str) -> None:
        full_path = self._vault_root / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
