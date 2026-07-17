from __future__ import annotations

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
