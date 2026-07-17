from __future__ import annotations

from fastapi.testclient import TestClient

from megachud.api.app import create_app
from megachud.config import ModelProfileConfig, ModelRoutingConfig, Settings


def make_settings_with_profiles(tmp_path) -> Settings:
    workspace = tmp_path / "ws"
    vault = tmp_path / "vault"
    workspace.mkdir()
    vault.mkdir()
    return Settings(
        workspace_root=workspace,
        db_path=tmp_path / "t.db",
        vault_root=vault,
        model_routing=ModelRoutingConfig(
            profiles=[
                ModelProfileConfig(
                    name="fast-cheap", cost_per_1k_input_tokens=0.0001, cost_per_1k_output_tokens=0.0002,
                    quality_tier=1, est_latency_ms=200,
                ),
                ModelProfileConfig(
                    name="balanced", cost_per_1k_input_tokens=0.001, cost_per_1k_output_tokens=0.003,
                    quality_tier=2, est_latency_ms=800,
                ),
                ModelProfileConfig(
                    name="premium", cost_per_1k_input_tokens=0.005, cost_per_1k_output_tokens=0.015,
                    quality_tier=3, est_latency_ms=1800,
                ),
            ]
        ),
    )


def test_list_profiles_echoes_config(tmp_path):
    settings = make_settings_with_profiles(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/routing/profiles")
        assert response.status_code == 200
        names = {p["name"] for p in response.json()}
        assert names == {"fast-cheap", "balanced", "premium"}


def test_simulate_route_picks_cheapest_qualifying_and_logs_event(tmp_path):
    settings = make_settings_with_profiles(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/routing/simulate",
            json={"task_type": "coding", "quality_target": 2, "est_tokens_input": 1000, "est_tokens_output": 500},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["chosen_model"] == "balanced"
        assert "premium" in payload["candidates_considered"]
        assert "fast-cheap" not in payload["candidates_considered"]

    # Verify the decision was logged as an Event, independent of the app's session.
    from megachud.db import get_engine, make_session_factory
    from megachud.models.event import Event

    engine = get_engine(settings.db_path)
    session_factory = make_session_factory(engine)
    session = session_factory()
    try:
        events = session.query(Event).filter_by(event_type="model_routing_decision").all()
        assert len(events) == 1
        assert events[0].task_id is None
    finally:
        session.close()


def test_simulate_route_with_unmeetable_quality_target_returns_422(tmp_path):
    settings = make_settings_with_profiles(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post("/routing/simulate", json={"task_type": "coding", "quality_target": 99})
        assert response.status_code == 422
