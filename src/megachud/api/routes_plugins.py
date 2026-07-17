from __future__ import annotations

from fastapi import APIRouter, Request

from megachud.api.schemas import PluginLoadResultSummary

router = APIRouter()


@router.get("/plugins", response_model=list[PluginLoadResultSummary])
def list_plugins(request: Request) -> list[PluginLoadResultSummary]:
    """Read-only — reflects the load results captured once at startup.
    Plugins reload only on restart, so this is all that's operationally
    meaningful; no live enable/disable from the UI."""
    results = request.app.state.plugin_load_results
    return [
        PluginLoadResultSummary(name=r.name, source=r.source, success=r.success, error=r.error) for r in results
    ]
