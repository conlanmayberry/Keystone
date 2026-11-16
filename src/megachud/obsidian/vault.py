from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from megachud.models.memory_entry import MemoryEntry
from megachud.models.reflection import Reflection
from megachud.models.task import Task
from megachud.obsidian import templates
from megachud.obsidian.research import ResearchNote

# Windows forbids these outright; the rest are stripped because they carry
# meaning inside an Obsidian wikilink and would break the link to this note.
_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\[\]#^]')


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

    def write_research_note(
        self,
        note: ResearchNote,
        *,
        folder: str = "research",
        sources: list[str] | None = None,
        task: Task | None = None,
    ) -> Path:
        """Named by title, not by UUID like the other two writers.

        This is the only note type a human is expected to open, search for,
        and link to by hand, so the filename has to be the title — a
        `[[research/9f3c…]]` wikilink is useless in a personal vault. That
        means collisions are possible, so an existing file is never
        overwritten: a numeric suffix is appended instead. Losing an
        earlier note to a same-titled later one would be silent data loss
        in the user's own vault.
        """
        slug = _slugify(note.title)
        relative = Path(folder) / f"{_unique_stem(self._vault_root / folder, slug)}.md"
        self._write(relative, templates.render_research_note(note, sources or [], task))
        return relative

    def _write(self, relative_path: Path, content: str) -> None:
        full_path = self._vault_root / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")


def _slugify(title: str) -> str:
    """Keeps spaces and case — this is an Obsidian note title, not a URL.
    Only strips what a filesystem or a wikilink can't carry.
    """
    normalized = unicodedata.normalize("NFC", title)
    cleaned = _UNSAFE_FILENAME_CHARS.sub("", normalized)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    # 120 chars leaves room for a " 2" suffix and the folder prefix inside
    # Windows' 260-char path limit.
    cleaned = cleaned[:120].strip()
    return cleaned or "Untitled research note"


def _unique_stem(folder: Path, slug: str) -> str:
    if not (folder / f"{slug}.md").exists():
        return slug
    counter = 2
    while (folder / f"{slug} {counter}.md").exists():
        counter += 1
    return f"{slug} {counter}"
