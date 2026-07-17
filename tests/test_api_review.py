from __future__ import annotations

from fastapi.testclient import TestClient

from megachud.api.app import create_app


def test_preview_hourly_does_not_persist(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        response = client.get("/reviews/hourly/preview")
        assert response.status_code == 200
        assert response.json()["kind"] == "hourly"
        assert response.json()["workflow_evolution"] is None

        listed = client.get("/reviews").json()
        assert listed == []


def test_generate_weekly_persists_and_lists(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        response = client.post("/reviews/weekly/generate")
        assert response.status_code == 200
        payload = response.json()
        assert payload["kind"] == "weekly"
        assert payload["workflow_evolution"] is not None
        assert payload["recommendations"] is not None

        listed = client.get("/reviews").json()
        assert len(listed) == 1
        assert listed[0]["kind"] == "weekly"

        filtered_hourly = client.get("/reviews?kind=hourly").json()
        assert filtered_hourly == []
        filtered_weekly = client.get("/reviews?kind=weekly").json()
        assert len(filtered_weekly) == 1


def test_unknown_kind_returns_422(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        assert client.get("/reviews/bogus/preview").status_code == 422
        assert client.post("/reviews/bogus/generate").status_code == 422
        assert client.get("/reviews?kind=bogus").status_code == 422
