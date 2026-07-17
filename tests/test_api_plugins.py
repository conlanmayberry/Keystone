from __future__ import annotations

from fastapi.testclient import TestClient

from megachud.api.app import create_app
from megachud.config import PluginsConfig, Settings


def test_no_plugins_configured_returns_empty_list(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as client:
        response = client.get("/plugins")
        assert response.status_code == 200
        assert response.json() == []


def test_enabled_plugin_appears_in_results(tmp_path):
    workspace = tmp_path / "ws"
    vault = tmp_path / "vault"
    workspace.mkdir()
    vault.mkdir()

    settings = Settings(
        workspace_root=workspace,
        db_path=tmp_path / "t.db",
        vault_root=vault,
        plugins=PluginsConfig(enabled_local=["does_not_exist"]),
    )

    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/plugins")
        assert response.status_code == 200
        results = response.json()
        assert len(results) == 1
        assert results[0]["name"] == "does_not_exist"
        assert results[0]["success"] is False
        assert "no such plugin file" in results[0]["error"]
