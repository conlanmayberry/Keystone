from __future__ import annotations

import json

from sqlalchemy.orm import Session, sessionmaker

from megachud.models.evaluation import Evaluation
from megachud.models.event import Event
from megachud.models.reflection import Reflection
from megachud.models.task import Task
from megachud.reflection.generator import DeterministicReflectionGenerator, ReflectionGenerator


class ReflectionEngine:
    def __init__(self, session_factory: sessionmaker[Session], generator: ReflectionGenerator | None = None) -> None:
        self._session_factory = session_factory
        self._generator = generator or DeterministicReflectionGenerator()

    def reflect(self, task_id: str) -> tuple[Task, Reflection]:
        session = self._session_factory()
        try:
            task = session.get(Task, task_id)
            evaluation = (
                session.query(Evaluation)
                .filter_by(task_id=task_id)
                .order_by(Evaluation.id.desc())
                .first()
            )
            events = session.query(Event).filter_by(task_id=task_id).order_by(Event.id).all()

            draft = self._generator.generate(task, evaluation, events)

            reflection = Reflection(
                task_id=task_id,
                evaluation_id=evaluation.id if evaluation is not None else None,
                what_worked=json.dumps(draft.what_worked),
                what_failed=json.dumps(draft.what_failed),
                wrong_assumptions=json.dumps(draft.wrong_assumptions),
                should_change=json.dumps(draft.should_change),
                become_long_term_knowledge=draft.become_long_term_knowledge,
            )
            session.add(reflection)
            session.commit()
            session.refresh(reflection)
            session.expunge(reflection)
            session.expunge(task)
            return task, reflection
        finally:
            session.close()
