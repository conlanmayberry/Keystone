from __future__ import annotations

from fastapi.testclient import TestClient

from megachud.api.app import create_app


def test_meta_echoes_default_names(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        response = client.get("/meta")
        assert response.status_code == 200
        assert response.json() == {"project_name": "default", "agent_name": "default"}
