from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from sqlalchemy.orm import Session, sessionmaker

from megachud.memory.vectorizer import embed
from megachud.models.memory_entry import MemoryEntry, MemoryType

MEMORY_DIRS = (MemoryType.EPISODIC.value, MemoryType.SEMANTIC.value, MemoryType.USER.value)


@dataclass
class ReindexReport:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def reindex_vault(vault_root: Path, session_factory: sessionmaker[Session], vector_dim: int) -> ReindexReport:
    """Walk vault/{episodic,semantic,user}/*.md, parse frontmatter (manual
    '---'-delimited split + yaml.safe_load — no new dependency, config.py
    already imports pyyaml directly), and upsert into memory_entries by the
    stable `id` stored in frontmatter. Human edits win: existing rows get
    their content/title/tags overwritten and re-embedded from the file.
    vault/tasks/*.md is read-only from this script's perspective — Task is
    Phase 1's canonical entity, not something the vault should mutate.
    """
    report = ReindexReport()
    for type_name in MEMORY_DIRS:
        dir_path = vault_root / type_name
        if not dir_path.exists():
            continue
        for md_file in sorted(dir_path.glob("*.md")):
            try:
                _reindex_file(md_file, session_factory, vector_dim, report)
            except Exception as exc:  # noqa: BLE001 - one bad note shouldn't abort the whole reindex
                report.errors.append(f"{md_file}: {exc}")
    return report


def _reindex_file(md_file: Path, session_factory: sessionmaker[Session], vector_dim: int, report: ReindexReport) -> None:
    parsed = _parse_frontmatter(md_file.read_text(encoding="utf-8"))
    if parsed is None:
        report.skipped += 1
        return
    frontmatter, body = parsed

    entry_type = frontmatter.get("type")
    entry_id = frontmatter.get("id")
    if entry_type not in MEMORY_DIRS or not entry_id:
        report.skipped += 1
        return

    title = _extract_title(body)
    content = _extract_content(body)
    tags = frontmatter.get("tags") or []
    embedding = embed(content, vector_dim)

    session = session_factory()
    try:
        existing = session.get(MemoryEntry, entry_id)
        if existing is not None:
            existing.title = title
            existing.content = content
            existing.tags_json = json.dumps(tags)
            existing.embedding_json = json.dumps(embedding)
            session.commit()
            report.updated += 1
        else:
            new_entry = MemoryEntry(
                id=entry_id,
                memory_type=MemoryType(entry_type),
                title=title,
                content=content,
                source_task_id=frontmatter.get("task_id"),
                tags_json=json.dumps(tags),
                importance=frontmatter.get("importance", 0.5),
                embedding_json=json.dumps(embedding),
            )
            session.add(new_entry)
            session.commit()
            report.created += 1
    finally:
        session.close()


def _parse_frontmatter(text: str) -> tuple[dict, str] | None:
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    _, raw_frontmatter, body = parts
    frontmatter = yaml.safe_load(raw_frontmatter) or {}
    return frontmatter, body.strip()


def _extract_title(body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _extract_content(body: str) -> str:
    lines = body.splitlines()
    content_lines: list[str] = []
    started = False
    for line in lines:
        if line.startswith("# ") and not started:
            started = True
            continue
        if line.strip() == "## Links":
            break
        if started:
            content_lines.append(line)
    return "\n".join(content_lines).strip()
