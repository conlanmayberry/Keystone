from __future__ import annotations

import importlib.metadata
import importlib.util
from dataclasses import dataclass
from pathlib import Path

from megachud.config import REPO_ROOT, Settings
from megachud.events.logger import EventLogger
from megachud.plugins.registry import PluginRegistry

DEFAULT_PLUGINS_DIR = REPO_ROOT / "plugins"


@dataclass
class PluginLoadResult:
    name: str
    source: str  # "local" | "package"
    success: bool
    error: str | None = None


def load_plugins(
    settings: Settings,
    registry: PluginRegistry,
    event_logger: EventLogger,
    plugins_dir: Path | None = None,
) -> list[PluginLoadResult]:
    """Scans two local-only sources, both requiring explicit config
    allow-listing — nothing loads unless named:
    1. settings.plugins.enabled_local: filenames (no .py) under
       plugins_dir (default the repo's top-level plugins/ directory).
    2. settings.plugins.enabled_packages: entry point names under group
       "megachud.plugins" from already pip-installed packages.

    Each plugin's import + register() call is wrapped in its own
    try/except — one plugin's exception never prevents another's load or
    the app's startup. Logs exactly one terminal Event per attempt.
    """
    plugins_dir = plugins_dir or DEFAULT_PLUGINS_DIR

    results = [_load_local_plugin(name, plugins_dir, registry, event_logger) for name in settings.plugins.enabled_local]
    results += [_load_package_plugin(name, registry, event_logger) for name in settings.plugins.enabled_packages]
    return results


def _load_local_plugin(
    name: str, plugins_dir: Path, registry: PluginRegistry, event_logger: EventLogger
) -> PluginLoadResult:
    plugin_path = plugins_dir / f"{name}.py"
    try:
        if not plugin_path.is_file():
            raise FileNotFoundError(f"no such plugin file: {plugin_path}")
        spec = importlib.util.spec_from_file_location(f"megachud_plugin_{name}", plugin_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"could not build an import spec for {plugin_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not hasattr(module, "register"):
            raise AttributeError(f"plugin {name!r} has no module-level register(registry) function")
        module.register(registry)
    except Exception as exc:  # noqa: BLE001 - one plugin's failure must never crash the app or block others
        return _log_result(event_logger, PluginLoadResult(name=name, source="local", success=False, error=str(exc)))
    return _log_result(event_logger, PluginLoadResult(name=name, source="local", success=True))


def _load_package_plugin(name: str, registry: PluginRegistry, event_logger: EventLogger) -> PluginLoadResult:
    try:
        entry_points = importlib.metadata.entry_points(group="megachud.plugins")
        matching = [ep for ep in entry_points if ep.name == name]
        if not matching:
            raise ImportError(f"no installed package declares entry point {name!r} under group 'megachud.plugins'")
        register_fn = matching[0].load()
        register_fn(registry)
    except Exception as exc:  # noqa: BLE001
        return _log_result(event_logger, PluginLoadResult(name=name, source="package", success=False, error=str(exc)))
    return _log_result(event_logger, PluginLoadResult(name=name, source="package", success=True))


def _log_result(event_logger: EventLogger, result: PluginLoadResult) -> PluginLoadResult:
    event_logger.log(
        event_type="plugin_load_succeeded" if result.success else "plugin_load_failed",
        payload={"name": result.name, "source": result.source, "error": result.error},
    )
    return result
