from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, SecretStr

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "default.yaml"
LOCAL_CONFIG_PATH = REPO_ROOT / "config" / "local.yaml"
DOTENV_PATH = REPO_ROOT / ".env"


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


class MemoryConfig(BaseModel):
    vector_dim: int = 512
    default_top_k: int = 5


class CuriosityConfig(BaseModel):
    similarity_threshold: float = 0.35
    research_objective_top_k: int = 3


class ExperimentConfig(BaseModel):
    default_minimum_sample_size: int = 10


class BottleneckConfig(BaseModel):
    window_days: int = 7
    min_samples: int = 5
    tool_failure_rate_threshold: float = 0.2


class ModelProfileConfig(BaseModel):
    name: str
    cost_per_1k_input_tokens: float
    cost_per_1k_output_tokens: float
    quality_tier: int
    est_latency_ms: int


class ModelRoutingConfig(BaseModel):
    profiles: list[ModelProfileConfig] = []
    default_quality_target: int = 2


class ReviewConfig(BaseModel):
    hourly_window_hours: int = 1
    weekly_window_days: int = 7


class PluginsConfig(BaseModel):
    enabled_local: list[str] = []
    enabled_packages: list[str] = []
    active_reflection_generator: str | None = None
    active_model_router: str | None = None


class FetchConfig(BaseModel):
    max_response_bytes: int = 2_000_000
    timeout_seconds: float = 15.0
    max_redirects: int = 5


class DownloadConfig(BaseModel):
    max_file_bytes: int = 25_000_000
    max_folder_bytes: int = 500_000_000
    blocked_extensions: list[str] = [
        ".exe", ".msi", ".bat", ".cmd", ".sh", ".ps1", ".dll", ".scr", ".com", ".jar",
    ]
    timeout_seconds: float = 30.0
    max_redirects: int = 5


class SearchConfig(BaseModel):
    max_results: int = 10
    timeout_seconds: float = 10.0


class InternetConfig(BaseModel):
    # Empty = unrestricted — fetching any public URL is allowed by default.
    domain_allowlist: list[str] = []
    domain_denylist: list[str] = []
    fetch: FetchConfig = FetchConfig()
    download: DownloadConfig = DownloadConfig()
    search: SearchConfig = SearchConfig()


class LLMConfig(BaseModel):
    default_reflection_model: str = "claude-haiku-4-5-20251001"
    default_planner_model: str = "claude-sonnet-5"
    default_curiosity_model: str = "claude-haiku-4-5-20251001"
    reflection_max_tokens: int = 4096
    planner_max_tokens: int = 4096
    # A question + 2 short descriptions needs far less than a full plan.
    curiosity_max_tokens: int = 1024
    timeout_seconds: float = 60.0


class Settings(BaseModel):
    workspace_root: Path
    db_path: Path
    vault_root: Path
    agent_name: str = "default"
    project_name: str = "default"
    # Never present in default.yaml/local.yaml — populated only from the
    # real environment or .env (see Settings.load / _load_dotenv below).
    # SecretStr so it never appears in a repr()/str() of this object.
    anthropic_api_key: SecretStr | None = None
    # Same rule: only from real env or .env. Only needed for the
    # web_search tool — http_fetch/download_file work with no key at all.
    brave_api_key: SecretStr | None = None
    api: ApiConfig = ApiConfig()
    approval: ApprovalConfig = ApprovalConfig()
    shell: ShellConfig = ShellConfig()
    evaluation: EvaluationConfig = EvaluationConfig()
    logging: LoggingConfig = LoggingConfig()
    memory: MemoryConfig = MemoryConfig()
    curiosity: CuriosityConfig = CuriosityConfig()
    experiment: ExperimentConfig = ExperimentConfig()
    bottleneck: BottleneckConfig = BottleneckConfig()
    model_routing: ModelRoutingConfig = ModelRoutingConfig()
    review: ReviewConfig = ReviewConfig()
    plugins: PluginsConfig = PluginsConfig()
    llm: LLMConfig = LLMConfig()
    internet: InternetConfig = InternetConfig()

    @classmethod
    def load(
        cls,
        default_path: Path = DEFAULT_CONFIG_PATH,
        local_path: Path = LOCAL_CONFIG_PATH,
        env_prefix: str = "MEGACHUD_",
        dotenv_path: Path = DOTENV_PATH,
    ) -> "Settings":
        data = _load_yaml(default_path)
        if local_path.exists():
            data = _deep_merge(data, _load_yaml(local_path))
        data = _apply_env_overrides(data, env_prefix)

        data["workspace_root"] = _resolve_path(data["workspace_root"])
        data["db_path"] = _resolve_path(data["db_path"])
        data["vault_root"] = _resolve_path(data["vault_root"])

        # A real env var always wins over .env; _load_dotenv never mutates
        # os.environ (unlike python-dotenv's load_dotenv()), so this has
        # zero global side effects and no cross-test leakage risk.
        dotenv_values = _load_dotenv(dotenv_path)
        data["anthropic_api_key"] = os.environ.get("ANTHROPIC_API_KEY") or dotenv_values.get("ANTHROPIC_API_KEY")
        data["brave_api_key"] = os.environ.get("BRAVE_API_KEY") or dotenv_values.get("BRAVE_API_KEY")

        return cls(**data)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_dotenv(dotenv_path: Path) -> dict[str, str]:
    """Returns parsed key/value pairs from dotenv_path via python-dotenv's
    dotenv_values() — never load_dotenv(), which mutates os.environ
    globally. Returns {} if the file doesn't exist. Pure function, no side
    effects: safe to call repeatedly in tests with zero cross-test leakage.
    """
    if not dotenv_path.is_file():
        return {}
    from dotenv import dotenv_values

    return {k: v for k, v in dotenv_values(dotenv_path).items() if v is not None}


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
        "vault_root": os.environ.get(f"{prefix}VAULT_ROOT"),
        "agent_name": os.environ.get(f"{prefix}AGENT_NAME"),
        "project_name": os.environ.get(f"{prefix}PROJECT_NAME"),
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
