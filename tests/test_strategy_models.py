from __future__ import annotations

from megachud.models.strategy import Strategy, StrategyOrigin


def test_strategy_roundtrip(db_session):
    strategy = Strategy(
        workflow_name="write_and_verify",
        version=1,
        is_active=True,
        title="Write a file and read it back",
        plan_template_json='[{"tool_name": "write_file", "args": {"path": "{filename}", "content": "{body}"}}]',
        parameters_json='["filename", "body"]',
        tags_json='["file_io"]',
    )
    db_session.add(strategy)
    db_session.commit()

    fetched = db_session.get(Strategy, strategy.id)
    assert fetched.workflow_name == "write_and_verify"
    assert fetched.is_active is True
    assert fetched.origin == StrategyOrigin.SEED
    assert fetched.sample_count == 0
    assert fetched.mean_score is None


def test_success_rate_property():
    strategy = Strategy(workflow_name="w", title="t", sample_count=0, success_count=0)
    assert strategy.success_rate == 0.0

    strategy.sample_count = 4
    strategy.success_count = 3
    assert strategy.success_rate == 0.75


def test_experiment_variant_links_to_parent(db_session):
    parent = Strategy(workflow_name="w", title="parent", is_active=True)
    db_session.add(parent)
    db_session.commit()

    variant = Strategy(
        workflow_name="w",
        title="challenger",
        origin=StrategyOrigin.EXPERIMENT_VARIANT,
        parent_strategy_id=parent.id,
    )
    db_session.add(variant)
    db_session.commit()

    fetched = db_session.get(Strategy, variant.id)
    assert fetched.parent_strategy_id == parent.id
    assert fetched.origin == StrategyOrigin.EXPERIMENT_VARIANT
