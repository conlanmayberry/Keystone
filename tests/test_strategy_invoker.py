from __future__ import annotations

import json

import pytest

from megachud.models.strategy import Strategy
from megachud.strategy.invoker import StrategyParameterError, invoke_strategy, render_plan


def make_strategy(session_factory, plan_template, parameters=None):
    session = session_factory()
    try:
        strategy = Strategy(
            workflow_name="demo_workflow",
            version=1,
            is_active=True,
            title="demo strategy",
            plan_template_json=json.dumps(plan_template),
            parameters_json=json.dumps(parameters or []),
        )
        session.add(strategy)
        session.commit()
        return strategy.id
    finally:
        session.close()


def test_render_plan_substitutes_multi_key_template_without_crashing(session_factory):
    # This is exactly the shape that would crash a naive
    # json.dumps(template).format(**params) implementation: multiple JSON
    # object keys mean multiple literal '{' characters colliding with
    # str.format()'s placeholder syntax.
    plan_template = [
        {"tool_name": "write_file", "args": {"path": "{filename}", "content": "{body}"}},
        {"tool_name": "read_file", "args": {"path": "{filename}"}},
    ]
    strategy_id = make_strategy(session_factory, plan_template, parameters=["filename", "body"])

    session = session_factory()
    try:
        strategy = session.get(Strategy, strategy_id)
        rendered = render_plan(strategy, {"filename": "out.txt", "body": "hello"})
    finally:
        session.close()

    assert rendered[0]["args"]["path"] == "out.txt"
    assert rendered[0]["args"]["content"] == "hello"
    assert rendered[1]["args"]["path"] == "out.txt"


def test_render_plan_raises_on_missing_parameter(session_factory):
    strategy_id = make_strategy(
        session_factory,
        [{"tool_name": "write_file", "args": {"path": "{filename}", "content": "x"}}],
        parameters=["filename"],
    )

    session = session_factory()
    try:
        strategy = session.get(Strategy, strategy_id)
        with pytest.raises(StrategyParameterError):
            render_plan(strategy, {})
    finally:
        session.close()


def test_render_plan_with_no_parameters_returns_template_unchanged(session_factory):
    plan_template = [{"tool_name": "read_file", "args": {"path": "fixed.txt"}}]
    strategy_id = make_strategy(session_factory, plan_template)

    session = session_factory()
    try:
        strategy = session.get(Strategy, strategy_id)
        rendered = render_plan(strategy, {})
    finally:
        session.close()

    assert rendered == plan_template


def test_invoke_strategy_creates_task_with_rendered_plan(session_factory):
    plan_template = [{"tool_name": "write_file", "args": {"path": "{filename}", "content": "hi"}}]
    strategy_id = make_strategy(session_factory, plan_template, parameters=["filename"])

    task_id = invoke_strategy(session_factory, strategy_id, {"filename": "a.txt"})

    session = session_factory()
    try:
        from megachud.models.task import Task

        task = session.get(Task, task_id)
        assert task is not None
        plan = json.loads(task.plan_json)
        assert plan[0]["args"]["path"] == "a.txt"
        assert "demo_workflow" in task.title
    finally:
        session.close()


def test_invoke_strategy_raises_on_unknown_strategy(session_factory):
    with pytest.raises(KeyError):
        invoke_strategy(session_factory, "does-not-exist", {})
