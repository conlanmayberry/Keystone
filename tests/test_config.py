from __future__ import annotations

import yaml

from megachud.config import Settings


def test_default_load_reads_repo_default_yaml():
    settings = Settings.load()

    assert settings.api.port == 8000
    assert settings.approval.timeout_seconds == 3600
    assert "python" in settings.shell.allowlist
    assert "rm" in settings.shell.denylist
    assert settings.workspace_root.name == "workspace"
    assert settings.db_path.name == "megachud.db"


def test_local_override_takes_precedence(tmp_path, monkeypatch):
    default_path = tmp_path / "default.yaml"
    local_path = tmp_path / "local.yaml"
    default_path.write_text(
        yaml.safe_dump({"workspace_root": "./workspace", "db_path": "./data/db.sqlite", "api": {"port": 8000}}),
        encoding="utf-8",
    )
    local_path.write_text(yaml.safe_dump({"api": {"port": 9999}}), encoding="utf-8")

    settings = Settings.load(default_path=default_path, local_path=local_path)

    assert settings.api.port == 9999


def test_env_override_takes_precedence_over_yaml(tmp_path, monkeypatch):
    default_path = tmp_path / "default.yaml"
    default_path.write_text(
        yaml.safe_dump({"workspace_root": "./workspace", "db_path": "./data/db.sqlite"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MEGACHUD_DB_PATH", str(tmp_path / "override.db"))

    settings = Settings.load(default_path=default_path, local_path=tmp_path / "missing.yaml")

    assert settings.db_path == tmp_path / "override.db"
