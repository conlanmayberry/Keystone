from __future__ import annotations

from fastapi.testclient import TestClient

from megachud.api.app import create_app


def test_default_agent_seeded_at_startup(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        response = client.get("/agents")
        assert response.status_code == 200
        names = [a["name"] for a in response.json()]
        assert names == ["default"]


def test_custom_agent_name_seeds_that_agent(tmp_path):
    from megachud.config import Settings

    settings = Settings(
        workspace_root=tmp_path / "ws",
        db_path=tmp_path / "t.db",
        vault_root=tmp_path / "vault",
        agent_name="worker-1",
    )
    (tmp_path / "ws").mkdir()
    (tmp_path / "vault").mkdir()

    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/agents")
        names = [a["name"] for a in response.json()]
        assert names == ["worker-1"]
