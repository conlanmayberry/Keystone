from __future__ import annotations

from megachud.memory.store import MemoryStore
from megachud.models.event import Event
from megachud.obsidian.vault import VaultWriter
from megachud.reflection.engine import ReflectionEngine


class TaskCompletionHandler:
    """Wired as EventLogger's `on_event` callback. Fires the deterministic
    reflection -> memory -> vault pipeline the moment a task finishes,
    regardless of caller (API request thread via the executor, or a
    standalone script) — no special-casing needed since both paths log
    through the same EventLogger.
    """

    def __init__(self, reflection_engine: ReflectionEngine, memory_store: MemoryStore, vault_writer: VaultWriter) -> None:
        self._reflection_engine = reflection_engine
        self._memory_store = memory_store
        self._vault_writer = vault_writer

    def __call__(self, event: Event) -> None:
        if event.event_type not in ("task_completed", "task_failed") or event.task_id is None:
            return

        task, reflection = self._reflection_engine.reflect(event.task_id)
        entries = self._memory_store.create_episodic_from_reflection(task, reflection)

        self._vault_writer.write_task_note(task, reflection, entries)
        for entry in entries:
            relative_path = self._vault_writer.write_memory_entry(entry, task)
            self._memory_store.set_vault_path(entry.id, str(relative_path))
