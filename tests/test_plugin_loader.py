from __future__ import annotations

from pathlib import Path

from megachud.config import Settings, PluginsConfig
from megachud.events.bus import EventBus
from megachud.events.logger import EventLogger
from megachud.models.event import Event
from megachud.plugins.loader import load_plugins
from megachud.plugins.registry import PluginRegistry
from megachud.tools.base import RiskLevel, Tool, ToolResult
from megachud.tools.registry import ToolRegistry

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class _FakeWriteFile(Tool):
    name = "write_file"
    description = "d"
    risk_level = RiskLevel.MEDIUM

    def validate_args(self, args):
        pass

    def run(self, args):
        return ToolResult(success=True, output="x")


def make_settings(tmp_path, **plugins_kwargs) -> Settings:
    return Settings(
        workspace_root=tmp_path / "ws",
        db_path=tmp_path / "t.db",
        vault_root=tmp_path / "vault",
        plugins=PluginsConfig(**plugins_kwargs),
    )


def test_good_local_plugin_loads_and_registers_tool(session_factory, tmp_path):
    settings = make_settings(tmp_path, enabled_local=["dummy_plugin"])
    tool_registry = ToolRegistry()
    plugin_registry = PluginRegistry(tool_registry)
    event_logger = EventLogger(session_factory, EventBus())

    results = load_plugins(settings, plugin_registry, event_logger, plugins_dir=FIXTURES_DIR)

    assert len(results) == 1
    assert results[0].success is True
    assert results[0].source == "local"
    assert tool_registry.get("dummy_plugin_tool") is not None


def test_broken_local_plugin_fails_gracefully(session_factory, tmp_path):
    settings = make_settings(tmp_path, enabled_local=["dummy_plugin_broken"])
    plugin_registry = PluginRegistry(ToolRegistry())
    event_logger = EventLogger(session_factory, EventBus())

    results = load_plugins(settings, plugin_registry, event_logger, plugins_dir=FIXTURES_DIR)

    assert len(results) == 1
    assert results[0].success is False
    assert "intentionally broken" in results[0].error


def test_good_and_broken_plugins_coexist_one_failure_does_not_block_others(session_factory, tmp_path):
    settings = make_settings(tmp_path, enabled_local=["dummy_plugin_broken", "dummy_plugin"])
    tool_registry = ToolRegistry()
    plugin_registry = PluginRegistry(tool_registry)
    event_logger = EventLogger(session_factory, EventBus())

    results = load_plugins(settings, plugin_registry, event_logger, plugins_dir=FIXTURES_DIR)

    assert len(results) == 2
    assert {r.name: r.success for r in results} == {"dummy_plugin_broken": False, "dummy_plugin": True}
    assert tool_registry.get("dummy_plugin_tool") is not None


def test_plugin_not_in_enabled_local_is_not_loaded(session_factory, tmp_path):
    # dummy_plugin.py exists on disk in FIXTURES_DIR but isn't named here.
    settings = make_settings(tmp_path, enabled_local=[])
    plugin_registry = PluginRegistry(ToolRegistry())
    event_logger = EventLogger(session_factory, EventBus())

    results = load_plugins(settings, plugin_registry, event_logger, plugins_dir=FIXTURES_DIR)

    assert results == []


def test_missing_local_plugin_file_is_a_captured_failure(session_factory, tmp_path):
    settings = make_settings(tmp_path, enabled_local=["does_not_exist"])
    plugin_registry = PluginRegistry(ToolRegistry())
    event_logger = EventLogger(session_factory, EventBus())

    results = load_plugins(settings, plugin_registry, event_logger, plugins_dir=FIXTURES_DIR)

    assert len(results) == 1
    assert results[0].success is False
    assert "no such plugin file" in results[0].error


def test_duplicate_tool_name_is_captured_failure_not_uncaught_exception(session_factory, tmp_path):
    settings = make_settings(tmp_path, enabled_local=["dummy_plugin_duplicate_name"])
    tool_registry = ToolRegistry()
    tool_registry.register(_FakeWriteFile())
    plugin_registry = PluginRegistry(tool_registry)
    event_logger = EventLogger(session_factory, EventBus())

    results = load_plugins(settings, plugin_registry, event_logger, plugins_dir=FIXTURES_DIR)

    assert len(results) == 1
    assert results[0].success is False
    assert "already registered" in results[0].error


def test_no_risk_level_plugin_is_captured_failure(session_factory, tmp_path):
    settings = make_settings(tmp_path, enabled_local=["dummy_plugin_no_risk_level"])
    plugin_registry = PluginRegistry(ToolRegistry())
    event_logger = EventLogger(session_factory, EventBus())

    results = load_plugins(settings, plugin_registry, event_logger, plugins_dir=FIXTURES_DIR)

    assert len(results) == 1
    assert results[0].success is False
    assert "risk_level" in results[0].error


def test_load_results_are_logged_as_events(session_factory, tmp_path):
    settings = make_settings(tmp_path, enabled_local=["dummy_plugin", "dummy_plugin_broken"])
    plugin_registry = PluginRegistry(ToolRegistry())
    event_logger = EventLogger(session_factory, EventBus())

    load_plugins(settings, plugin_registry, event_logger, plugins_dir=FIXTURES_DIR)

    session = session_factory()
    try:
        succeeded = session.query(Event).filter_by(event_type="plugin_load_succeeded").all()
        failed = session.query(Event).filter_by(event_type="plugin_load_failed").all()
        assert len(succeeded) == 1
        assert len(failed) == 1
    finally:
        session.close()


def test_package_plugin_no_matching_entry_point_is_captured_failure(session_factory, tmp_path):
    settings = make_settings(tmp_path, enabled_packages=["nonexistent_package_plugin"])
    plugin_registry = PluginRegistry(ToolRegistry())
    event_logger = EventLogger(session_factory, EventBus())

    results = load_plugins(settings, plugin_registry, event_logger, plugins_dir=FIXTURES_DIR)

    assert len(results) == 1
    assert results[0].source == "package"
    assert results[0].success is False
    assert "no installed package declares entry point" in results[0].error


def test_package_plugin_matching_entry_point_loads(session_factory, tmp_path, monkeypatch):
    import megachud.plugins.loader as loader_module

    calls = []

    class FakeEntryPoint:
        name = "fake_package_plugin"

        def load(self):
            return lambda registry: calls.append(registry)

    def fake_entry_points(*, group):
        assert group == "megachud.plugins"
        return [FakeEntryPoint()]

    monkeypatch.setattr(loader_module.importlib.metadata, "entry_points", fake_entry_points)

    settings = make_settings(tmp_path, enabled_packages=["fake_package_plugin"])
    plugin_registry = PluginRegistry(ToolRegistry())
    event_logger = EventLogger(session_factory, EventBus())

    results = load_plugins(settings, plugin_registry, event_logger, plugins_dir=FIXTURES_DIR)

    assert len(results) == 1
    assert results[0].success is True
    assert len(calls) == 1
