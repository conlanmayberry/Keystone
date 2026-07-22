from __future__ import annotations

import pytest
from pydantic import SecretStr

from megachud.api.app import create_app


def test_create_app_does_not_raise_with_no_api_key(test_settings):
    assert test_settings.anthropic_api_key is None

    app = create_app(test_settings)

    assert app.state.llm_client is None
    assert app.state.llm_task_planner is None
    assert app.state.model_profiles == []


def test_http_fetch_tool_always_registered(test_settings):
    app = create_app(test_settings)
    tool = app.state.tool_registry.get("http_fetch")
    assert tool.name == "http_fetch"


def test_download_file_tool_always_registered(test_settings):
    app = create_app(test_settings)
    tool = app.state.tool_registry.get("download_file")
    assert tool.name == "download_file"


def test_web_search_not_registered_without_brave_key(test_settings):
    assert test_settings.brave_api_key is None
    app = create_app(test_settings)
    with pytest.raises(KeyError):
        app.state.tool_registry.get("web_search")


def test_web_search_registered_with_brave_key(test_settings):
    settings = test_settings.model_copy(update={"brave_api_key": SecretStr("brave-test-key")})
    app = create_app(settings)
    tool = app.state.tool_registry.get("web_search")
    assert tool.name == "web_search"


def test_browser_read_only_tools_always_registered(test_settings):
    app = create_app(test_settings)
    assert app.state.tool_registry.get("browser_navigate").name == "browser_navigate"
    assert app.state.tool_registry.get("browser_read").name == "browser_read"
    assert app.state.browser_manager is not None


def test_browser_interaction_tools_registered(test_settings):
    from megachud.models.approval import RiskLevel

    app = create_app(test_settings)
    registry = app.state.tool_registry
    assert registry.get("browser_fill").name == "browser_fill"
    assert registry.get("browser_click").name == "browser_click"
    assert registry.get("browser_submit").risk_level == RiskLevel.HIGH_IRREVERSIBLE
