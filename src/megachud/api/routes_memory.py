from __future__ import annotations

import json

from fastapi import APIRouter, Request

from megachud.api.schemas import MemoryCreateRequest, MemoryEntrySummary, MemorySearchResult
from megachud.memory.retrieval import search
from megachud.models.memory_entry import MemoryEntry, MemoryType
from megachud.obsidian.reindex import reindex_vault
from megachud.obsidian.vault import VaultWriter

router = APIRouter()


def _to_summary(entry: MemoryEntry) -> MemoryEntrySummary:
    return MemoryEntrySummary(
        id=entry.id,
        memory_type=entry.memory_type.value,
        title=entry.title,
        content=entry.content,
        tags=json.loads(entry.tags_json),
        created_at=entry.created_at.isoformat(),
        source_task_id=entry.source_task_id,
        vault_path=entry.vault_path,
    )


@router.get("/memory", response_model=list[MemoryEntrySummary])
def list_memory(request: Request, type: str | None = None, limit: int = 50) -> list[MemoryEntrySummary]:
    store = request.app.state.memory_store
    if type:
        entries = store.list_by_type(MemoryType(type), limit=limit)
    else:
        entries = []
        for memory_type in MemoryType:
            entries += store.list_by_type(memory_type, limit=limit)
        entries.sort(key=lambda e: e.created_at, reverse=True)
        entries = entries[:limit]
    return [_to_summary(entry) for entry in entries]


@router.get("/memory/search", response_model=list[MemorySearchResult])
def search_memory(request: Request, q: str, type: str | None = None, top_k: int = 5) -> list[MemorySearchResult]:
    settings = request.app.state.settings
    memory_type = MemoryType(type) if type else None
    results = search(
        request.app.state.session_factory,
        q,
        settings.memory.vector_dim,
        memory_type=memory_type,
        top_k=top_k,
    )
    return [MemorySearchResult(entry=_to_summary(result.entry), score=result.score) for result in results]


@router.post("/memory/user", response_model=MemoryEntrySummary)
def create_user_memory(payload: MemoryCreateRequest, request: Request) -> MemoryEntrySummary:
    store = request.app.state.memory_store
    settings = request.app.state.settings

    entry = store.create_user_entry(content=payload.content, title=payload.title, tags=payload.tags)

    vault_writer = VaultWriter(settings.vault_root)
    relative_path = vault_writer.write_memory_entry(entry, None)
    store.set_vault_path(entry.id, str(relative_path))

    return _to_summary(store.get(entry.id))


@router.post("/memory/reindex")
def reindex(request: Request) -> dict:
    settings = request.app.state.settings
    report = reindex_vault(settings.vault_root, request.app.state.session_factory, settings.memory.vector_dim)
    return {
        "created": report.created,
        "updated": report.updated,
        "skipped": report.skipped,
        "errors": report.errors,
    }
