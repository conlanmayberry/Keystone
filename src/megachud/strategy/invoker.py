from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from megachud.models.strategy import Strategy
from megachud.models.task import Task


class StrategyParameterError(ValueError):
    pass


def render_plan(strategy: Strategy, params: dict[str, Any]) -> list[dict]:
    """Substitutes '{param_name}' placeholders on parsed leaf STRINGS only
    — recursing through the already-parsed template, never on the
    serialized JSON text. json.dumps(template).format(**params) would
    crash on any realistic template: JSON's own structural braces
    (e.g. `{"tool_name": ...}`) collide with str.format()'s placeholder
    syntax the moment a template has more than one key.
    """
    required = json.loads(strategy.parameters_json)
    missing = [p for p in required if p not in params]
    if missing:
        raise StrategyParameterError(f"missing parameters: {missing}")

    template = json.loads(strategy.plan_template_json)
    return _substitute(template, params)


def _substitute(node: Any, params: dict[str, Any]) -> Any:
    if isinstance(node, str):
        return node.format(**params) if params else node
    if isinstance(node, dict):
        return {key: _substitute(value, params) for key, value in node.items()}
    if isinstance(node, list):
        return [_substitute(value, params) for value in node]
    return node


def invoke_strategy(
    session_factory: sessionmaker[Session],
    strategy_id: str,
    params: dict[str, Any],
    title: str | None = None,
    agent_id: str | None = None,
    project_name: str | None = None,
) -> str:
    """Renders plan_json from the strategy template + params and inserts a
    Task row exactly the way routes_tasks.create_task does — no new
    Task-creation code path. Does not submit to the orchestrator itself;
    the caller does that and logs a 'strategy_invoked' event so
    strategy/metrics.py can find it later.
    """
    session = session_factory()
    try:
        strategy = session.get(Strategy, strategy_id)
        if strategy is None:
            raise KeyError(f"unknown strategy: {strategy_id!r}")

        plan = render_plan(strategy, params)
        task = Task(
            title=title or f"{strategy.workflow_name} v{strategy.version}",
            prompt=f"invoked from strategy {strategy.id} ({strategy.workflow_name} v{strategy.version})",
            plan_json=json.dumps(plan),
            agent_id=agent_id,
            project_name=project_name,
        )
        session.add(task)
        session.commit()
        return task.id
    finally:
        session.close()
