from __future__ import annotations

import json

from sqlalchemy.orm import Session, sessionmaker

from megachud.curiosity.llm_generator import CuriosityText, CuriosityTextGenerator, DeterministicCuriosityTextGenerator
from megachud.events.logger import EventLogger
from megachud.memory.retrieval import search
from megachud.models.curiosity import PendingQuestion, ResearchObjective
from megachud.models.event import Event
from megachud.models.memory_entry import MemoryType
from megachud.models.reflection import Reflection
from megachud.models.task import Task
from megachud.routing.engine import ModelProfile, compute_cost_usd, profile_by_name
from megachud.runtime.thoughts import ThoughtLog


class CuriosityHandler:
    """Wired into EventDispatcher AFTER TaskCompletionHandler (needs the
    Reflection it just created) and StrategyMetricsHandler. On
    task_completed/task_failed, if the just-created Reflection has
    become_long_term_knowledge=True, checks whether a close precedent
    already exists in SEMANTIC memory; if not, raises research objectives
    and a pending question — all local (no real web search this round).

    Question/objective TEXT can come from an LLM (text_generator) — the
    real local memory search, the self-match filter, the
    become_long_term_knowledge trigger gate, and the similarity-threshold
    comparison are all untouched regardless of which text_generator is
    configured.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        vector_dim: int,
        similarity_threshold: float,
        research_objective_top_k: int = 3,
        text_generator: CuriosityTextGenerator | None = None,
        event_logger: EventLogger | None = None,
        profiles: list[ModelProfile] | None = None,
        thought_log: ThoughtLog | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._vector_dim = vector_dim
        self._similarity_threshold = similarity_threshold
        self._top_k = research_objective_top_k
        self._text_generator = text_generator or DeterministicCuriosityTextGenerator()
        self._event_logger = event_logger
        self._profiles = profiles
        self._thought_log = thought_log

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

        text = self._text_generator.generate(task_title, task_prompt, best_score, self._similarity_threshold)
        self._log_cost_if_real(task_id, text)

        self._raise_research_objective(
            task_id, reflection_id, "search_memory", task_prompt, None, text.objective_descriptions["search_memory"]
        )
        self._raise_research_objective(
            task_id, reflection_id, "inspect_previous_work", task_title, MemoryType.EPISODIC,
            text.objective_descriptions["inspect_previous_work"],
        )
        self._raise_pending_question(task_id, reflection_id, text.question)
        if self._thought_log is not None:
            self._thought_log.record("curiosity", text.question)

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

    def _raise_research_objective(self, task_id, reflection_id, objective_type, query_text, memory_type, description):
        results = self._search_excluding_self(task_id, query_text, memory_type=memory_type, limit=self._top_k)
        findings = [{"memory_entry_id": r.entry.id, "title": r.entry.title, "score": r.score} for r in results]

        session = self._session_factory()
        try:
            objective = ResearchObjective(
                source_task_id=task_id,
                source_reflection_id=reflection_id,
                objective_type=objective_type,
                description=description,
                findings_json=json.dumps(findings),
                resolved=True,
            )
            session.add(objective)
            session.commit()
        finally:
            session.close()

    def _raise_pending_question(self, task_id, reflection_id, question):
        session = self._session_factory()
        try:
            pending = PendingQuestion(
                source_task_id=task_id,
                source_reflection_id=reflection_id,
                question=question,
                context=f"triggered by become_long_term_knowledge reflection {reflection_id}",
            )
            session.add(pending)
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

    def _log_cost_if_real(self, task_id: str, text: CuriosityText) -> None:
        # Only logs when real usage occurred — the deterministic path
        # (tokens 0/0) never produces a misleading llm_call event.
        if not (text.tokens_input or text.tokens_output):
            return
        if not self._event_logger or not self._profiles:
            return
        profile = profile_by_name(self._profiles, text.model)
        cost_usd = compute_cost_usd(profile, text.tokens_input, text.tokens_output) if profile is not None else None
        self._event_logger.log(
            event_type="llm_call",
            task_id=task_id,
            tool_name="llm:curiosity",
            cost_usd=cost_usd,
            tokens_input=text.tokens_input,
            tokens_output=text.tokens_output,
            payload={"model": text.model, "consumer": "curiosity"},
        )
