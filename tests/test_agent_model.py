from __future__ import annotations

from megachud.db import get_or_create_agent
from megachud.models.agent import Agent


def test_agent_roundtrip(db_session):
    agent = Agent(name="worker-1", description="a test agent")
    db_session.add(agent)
    db_session.commit()

    fetched = db_session.get(Agent, agent.id)
    assert fetched.name == "worker-1"
    assert fetched.description == "a test agent"


def test_get_or_create_agent_creates_once(session_factory):
    first_id = get_or_create_agent(session_factory, "default")
    second_id = get_or_create_agent(session_factory, "default")

    assert first_id == second_id

    session = session_factory()
    try:
        count = session.query(Agent).filter_by(name="default").count()
        assert count == 1
    finally:
        session.close()


def test_get_or_create_agent_distinguishes_names(session_factory):
    default_id = get_or_create_agent(session_factory, "default")
    worker_id = get_or_create_agent(session_factory, "worker-1")

    assert default_id != worker_id
