from __future__ import annotations

import json

from sqlalchemy.orm import Session, sessionmaker

from megachud.memory.retrieval import search
from megachud.models.curiosity import PendingQuestion, ResearchObjective
from megachud.models.event import Event
from megachud.models.memory_entry import MemoryType
from megachud.models.reflection import Reflection
from megachud.models.task import Task


class CuriosityHandler:
    """Wired into EventDispatcher AFTER TaskCompletionHandler (needs the
    Reflection it just created) and StrategyMetricsHandler. On
    task_completed/task_failed, if the just-created Reflection has
    become_long_term_knowledge=True, checks whether a close precedent
    already exists in SEMANTIC memory; if not, raises research objectives
    and a pending question — all local (no real web search this round).
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        vector_dim: int,
        similarity_threshold: float,
        research_objective_top_k: int = 3,
    ) -> None:
        self._session_factory = session_factory
        self._vector_dim = vector_dim
        self._similarity_threshold = similarity_threshold
        self._top_k = research_objective_top_k

    def __call__(self, event: Event) -> None:
        if event.event_type not in ("task_completed", "task_failed") or event.task_id is None:
            return

        session = self._session_factory()
        try:
            reflection = (
                session.query(Reflection)
                .filter_by(task_id=event.task_id)
                .order_by(Reflection.id.desc())
                .first()
            )
            if reflection is None or not reflection.become_long_term_knowledge:
                return
            task = session.get(Task, event.task_id)
            reflection_id, task_id, task_title, task_prompt = reflection.id, task.id, task.title, task.prompt
        finally:
            session.close()

        best_score = self._best_prior_similarity(task_id, task_prompt)
        if best_score >= self._similarity_threshold:
            return

        self._raise_research_objective(task_id, reflection_id, "search_memory", task_prompt, None)
        self._raise_research_objective(task_id, reflection_id, "inspect_previous_work", task_title, MemoryType.EPISODIC)
        self._raise_pending_question(task_id, reflection_id, task_title, best_score)

    def _best_prior_similarity(self, task_id: str, query_text: str) -> float:
        """CRITICAL self-match guard: excludes any result whose
        source_task_id == task_id. TaskCompletionHandler (which runs
        before this handler) just created this task's own semantic entry
        moments earlier in the same dispatch — without this filter, a
        task's own freshly-created memory would match itself and silently
        suppress curiosity every time become_long_term_knowledge is True
        after the very first case. Fetches a few extra candidates
        (top_k + 1) so a genuine second-best match survives the filter
        even if the top hit is the self-match.
        """
        results = self._search_excluding_self(task_id, query_text, memory_type=MemoryType.SEMANTIC, limit=1)
        return results[0].score if results else 0.0

    def _raise_research_objective(self, task_id, reflection_id, objective_type, query_text, memory_type):
        results = self._search_excluding_self(task_id, query_text, memory_type=memory_type, limit=self._top_k)
        findings = [{"memory_entry_id": r.entry.id, "title": r.entry.title, "score": r.score} for r in results]

        session = self._session_factory()
        try:
            objective = ResearchObjective(
                source_task_id=task_id,
                source_reflection_id=reflection_id,
                objective_type=objective_type,
                description=f"{objective_type} for: {query_text[:200]}",
                findings_json=json.dumps(findings),
                resolved=True,
            )
            session.add(objective)
            session.commit()
        finally:
            session.close()

    def _raise_pending_question(self, task_id, reflection_id, task_title, best_score):
        session = self._session_factory()
        try:
            question = PendingQuestion(
                source_task_id=task_id,
                source_reflection_id=reflection_id,
                question=(
                    f"Task {task_title!r} produced a lesson with no close precedent "
                    f"(best prior similarity {best_score:.2f} below threshold {self._similarity_threshold}). "
                    "What is the right general approach for similar future tasks?"
                ),
                context=f"triggered by become_long_term_knowledge reflection {reflection_id}",
            )
            session.add(question)
            session.commit()
        finally:
            session.close()

    def _search_excluding_self(self, task_id: str, query_text: str, memory_type, limit: int):
        results = search(
            self._session_factory,
            query_text,
            self._vector_dim,
            memory_type=memory_type,
            top_k=limit + 1,
        )
        return [r for r in results if r.entry.source_task_id != task_id][:limit]
