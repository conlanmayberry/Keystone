from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "default.yaml"
LOCAL_CONFIG_PATH = REPO_ROOT / "config" / "local.yaml"


class ApiConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000


class ApprovalConfig(BaseModel):
    timeout_seconds: int = 3600
    poll_interval_seconds: float = 0.5


class ShellConfig(BaseModel):
    allowlist: list[str] = []
    denylist: list[str] = []
    timeout_seconds: int = 120


class EvaluationConfig(BaseModel):
    test_command: str | None = None


class LoggingConfig(BaseModel):
    level: str = "INFO"


class Settings(BaseModel):
    workspace_root: Path
    db_path: Path
    api: ApiConfig = ApiConfig()
    approval: ApprovalConfig = ApprovalConfig()
    shell: ShellConfig = ShellConfig()
    evaluation: EvaluationConfig = EvaluationConfig()
    logging: LoggingConfig = LoggingConfig()

    @classmethod
    def load(
        cls,
        default_path: Path = DEFAULT_CONFIG_PATH,
        local_path: Path = LOCAL_CONFIG_PATH,
        env_prefix: str = "MEGACHUD_",
    ) -> "Settings":
        data = _load_yaml(default_path)
        if local_path.exists():
            data = _deep_merge(data, _load_yaml(local_path))
        data = _apply_env_overrides(data, env_prefix)

        data["workspace_root"] = _resolve_path(data["workspace_root"])
        data["db_path"] = _resolve_path(data["db_path"])

        return cls(**data)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _apply_env_overrides(data: dict[str, Any], prefix: str) -> dict[str, Any]:
    # Supports flat top-level overrides, e.g. MEGACHUD_DB_PATH, MEGACHUD_WORKSPACE_ROOT.
    overrides = {
        "db_path": os.environ.get(f"{prefix}DB_PATH"),
        "workspace_root": os.environ.get(f"{prefix}WORKSPACE_ROOT"),
    }
    result = dict(data)
    for key, value in overrides.items():
        if value is not None:
            result[key] = value
    return result


def _resolve_path(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path
