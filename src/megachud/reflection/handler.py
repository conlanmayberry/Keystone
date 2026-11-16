from __future__ import annotations

import json
import logging

from megachud.memory.store import MemoryStore
from megachud.models.event import Event
from megachud.models.memory_entry import MemoryEntry
from megachud.models.reflection import Reflection
from megachud.models.task import Task
from megachud.obsidian.research import ResearchSynthesisError, ResearchSynthesizer
from megachud.obsidian.vault import VaultWriter
from megachud.reflection.engine import ReflectionEngine

logger = logging.getLogger(__name__)


class TaskCompletionHandler:
    """Wired as EventLogger's `on_event` callback. Fires the deterministic
    reflection -> memory -> vault pipeline the moment a task finishes,
    regardless of caller (API request thread via the executor, or a
    standalone script) — no special-casing needed since both paths log
    through the same EventLogger.

    `research_synthesizer` is the one optional, LLM-backed step: when set,
    tasks whose reflection was judged long-term knowledge also get a
    synthesized research note written into the vault. It lives here rather
    than in its own dispatcher handler for one specific reason —
    ReflectionEngine.reflect() INSERTS a new Reflection row every call, so
    a second handler that re-derived the reflection would silently double
    every task's reflection history. This method already holds the task,
    reflection, and entries it needs.
    """

    def __init__(
        self,
        reflection_engine: ReflectionEngine,
        memory_store: MemoryStore,
        vault_writer: VaultWriter,
        research_synthesizer: ResearchSynthesizer | None = None,
        research_folder: str = "research",
    ) -> None:
        self._reflection_engine = reflection_engine
        self._memory_store = memory_store
        self._vault_writer = vault_writer
        self._research_synthesizer = research_synthesizer
        self._research_folder = research_folder

    def __call__(self, event: Event) -> None:
        if event.event_type not in ("task_completed", "task_failed") or event.task_id is None:
            return

        task, reflection = self._reflection_engine.reflect(event.task_id)
        entries = self._memory_store.create_episodic_from_reflection(task, reflection)

        self._vault_writer.write_task_note(task, reflection, entries)
        for entry in entries:
            relative_path = self._vault_writer.write_memory_entry(entry, task)
            self._memory_store.set_vault_path(entry.id, str(relative_path))

        self._maybe_write_research_note(task, reflection, entries)

    def _maybe_write_research_note(
        self, task: Task, reflection: Reflection, entries: list[MemoryEntry]
    ) -> None:
        """Gated on become_long_term_knowledge — the same signal that
        already decides whether a semantic memory is worth creating. Without
        that gate every routine task would cost an LLM call and drop another
        note into the user's vault.
        """
        if self._research_synthesizer is None or not reflection.become_long_term_knowledge:
            return

        try:
            note = self._research_synthesizer.synthesize(
                topic=task.title,
                findings=_render_findings(task, reflection, entries),
                task_id=task.id,
            )
            self._vault_writer.write_research_note(note, folder=self._research_folder, task=task)
        except ResearchSynthesisError as exc:
            # Never let an optional vault note break task completion — the
            # reflection, memory entries, and task note above are already
            # committed and are what the rest of the system depends on.
            logger.warning("research note synthesis skipped for task %s: %s", task.id, exc)
        except OSError as exc:
            logger.warning("could not write research note for task %s: %s", task.id, exc)


def _render_findings(task: Task, reflection: Reflection, entries: list[MemoryEntry]) -> str:
    lines = [f"Task: {task.title}", f"What was asked: {task.prompt}"]
    if task.result_summary:
        lines.append(f"Outcome: {task.result_summary}")

    for label, field_value in (
        ("What worked", reflection.what_worked),
        ("What failed", reflection.what_failed),
        ("Wrong assumptions", reflection.wrong_assumptions),
        ("What should change", reflection.should_change),
    ):
        items = json.loads(field_value)
        if items:
            lines.append(f"{label}:")
            lines += [f"  - {item}" for item in items]

    for entry in entries:
        lines += [f"Memory recorded ({entry.memory_type.value}) — {entry.title}:", entry.content]

    return "\n".join(lines)
