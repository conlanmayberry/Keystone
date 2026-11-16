from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from megachud.memory.vectorizer import embed

# Notes bigger than this are almost certainly not hand-written prose worth
# linking to (pasted logs, embedded data). Reading them in full on every
# scan would dominate the cost of indexing for no benefit.
_MAX_NOTE_BYTES = 200_000

_WIKILINK_RE = re.compile(r"\[\[([^\[\]|]+)(?:\|([^\[\]]+))?\]\]")


@dataclass(frozen=True)
class VaultNote:
    """One existing note in the user's vault, reduced to what a synthesis
    prompt needs: a human-facing `title` the LLM can reference, and the
    `link_target` that actually resolves inside Obsidian.
    """

    # What goes inside [[...]]: the bare filename stem when that stem is
    # unique vault-wide (Obsidian resolves those from anywhere), otherwise
    # the full vault-relative path so the link is unambiguous.
    link_target: str
    # The H1 or frontmatter title if the note has one, else the filename
    # stem. This is what the LLM sees and writes, because MegaChud's own
    # memory notes are named by UUID — `[[084a4be0-…]]` is useless to a
    # human and to a model, `[[084a4be0-…|Lesson: retries]]` is not.
    title: str
    excerpt: str
    relative_path: str


class VaultIndex:
    """Read-only view of an Obsidian vault, used to ground synthesis in
    notes that actually exist. Nothing here ever writes — the linking
    story is outbound-only, so a user's hand-written notes are never
    touched by MegaChud.

    Rescans on demand rather than caching a snapshot at startup: the vault
    is edited by a human in another application, so a stale index would
    silently produce links to notes that were since renamed. Per-file
    mtime caching keeps the rescan cheap after the first one.
    """

    def __init__(
        self,
        vault_root: Path,
        vector_dim: int,
        *,
        excerpt_chars: int = 400,
        max_notes: int = 2000,
        exclude_folders: tuple[str, ...] = (),
    ) -> None:
        self._vault_root = vault_root
        self._vector_dim = vector_dim
        self._excerpt_chars = excerpt_chars
        self._max_notes = max_notes
        # Top-level folders never offered as link candidates. Guidance
        # notes go here: they describe how to work, so a research note
        # linking to "Error Recovery" is noise in the knowledge graph.
        self._exclude_folders = tuple(folder.strip("/") for folder in exclude_folders if folder.strip("/"))
        self._cache: dict[Path, tuple[float, VaultNote]] = {}

    def scan(self) -> list[VaultNote]:
        notes: list[VaultNote] = []
        stem_counts: dict[str, int] = {}
        raw: list[tuple[Path, str, str, str]] = []  # path, relative, title, excerpt

        for md_file in sorted(self._iter_markdown()):
            parsed = self._read(md_file)
            if parsed is None:
                continue
            relative, title, excerpt = parsed
            stem = md_file.stem
            stem_counts[stem] = stem_counts.get(stem, 0) + 1
            raw.append((md_file, relative, title, excerpt))

        for md_file, relative, title, excerpt in raw:
            stem = md_file.stem
            # Ambiguous stems get the full path so Obsidian resolves the
            # link to the note we actually meant.
            link_target = stem if stem_counts[stem] == 1 else relative[: -len(".md")]
            notes.append(
                VaultNote(link_target=link_target, title=title, excerpt=excerpt, relative_path=relative)
            )
        return notes

    def relevant(self, query: str, top_k: int) -> list[VaultNote]:
        """Shortlist the notes most related to `query`, so the synthesis
        prompt carries a bounded, relevant slice of the vault instead of
        the whole thing. Reuses the same local HashingVectorizer that backs
        memory retrieval — no extra embedding API call, no extra cost.
        """
        notes = self.scan()
        if not notes or top_k <= 0:
            return []

        matrix = np.array(
            [embed(f"{note.title}\n{note.excerpt}", self._vector_dim) for note in notes],
            dtype=np.float32,
        )
        query_vec = np.array(embed(query, self._vector_dim), dtype=np.float32)
        scores = matrix @ query_vec

        ranked = np.argsort(-scores)[:top_k]
        # A zero score means no shared hashed n-gram at all — linking there
        # would be a fabricated connection, which is the one thing this
        # whole module exists to prevent.
        return [notes[int(i)] for i in ranked if scores[int(i)] > 0.0]

    def resolve_links(self, body: str, candidates: list[VaultNote]) -> tuple[str, list[VaultNote]]:
        """Rewrite every `[[...]]` in LLM-written markdown to a link that
        resolves, and strip the ones that don't.

        The model is given candidate *titles*, so it writes `[[Deep Work]]`.
        This maps that back to the real filename (`[[deep-work|Deep Work]]`
        when they differ) and demotes any wikilink naming a note that isn't
        in the candidate list to plain text. That demotion is the point:
        an unresolvable wikilink in Obsidian silently becomes an offer to
        create a new empty note, so a hallucinated link would quietly
        pollute the vault rather than fail loudly.
        """
        by_title = {note.title.strip().lower(): note for note in candidates}
        by_target = {note.link_target.strip().lower(): note for note in candidates}
        linked: dict[str, VaultNote] = {}

        def replace(match: re.Match[str]) -> str:
            name = match.group(1).strip()
            alias = (match.group(2) or "").strip()
            note = by_title.get(name.lower()) or by_target.get(name.lower())
            if note is None:
                return alias or name
            linked[note.link_target] = note
            display = alias or name
            if display.strip().lower() == note.link_target.strip().lower():
                return f"[[{note.link_target}]]"
            return f"[[{note.link_target}|{display}]]"

        return _WIKILINK_RE.sub(replace, body), list(linked.values())

    def _iter_markdown(self) -> list[Path]:
        if not self._vault_root.is_dir():
            return []
        found: list[Path] = []
        for md_file in self._vault_root.rglob("*.md"):
            parts = md_file.relative_to(self._vault_root).parts
            # Skips .obsidian/, .trash/, .git/ — config and deleted notes
            # are not things to link to.
            if any(part.startswith(".") for part in parts):
                continue
            if parts and parts[0] in self._exclude_folders:
                continue
            if not md_file.is_file():
                continue
            found.append(md_file)
            if len(found) >= self._max_notes:
                break
        return found

    def _read(self, md_file: Path) -> tuple[str, str, str] | None:
        try:
            stat = md_file.stat()
            if stat.st_size > _MAX_NOTE_BYTES:
                return None
            cached = self._cache.get(md_file)
            if cached is not None and cached[0] == stat.st_mtime:
                note = cached[1]
                return note.relative_path, note.title, note.excerpt
            text = md_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        relative = md_file.relative_to(self._vault_root).as_posix()
        frontmatter, body = _split_frontmatter(text)
        title = str(frontmatter.get("title") or "").strip() or _first_heading(body) or md_file.stem
        excerpt = _excerpt(body, self._excerpt_chars)

        self._cache[md_file] = (
            stat.st_mtime,
            VaultNote(link_target=md_file.stem, title=title, excerpt=excerpt, relative_path=relative),
        )
        return relative, title, excerpt


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        frontmatter = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        frontmatter = {}
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return frontmatter, parts[2]


def _first_heading(body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _excerpt(body: str, max_chars: int) -> str:
    lines = [line.strip() for line in body.splitlines()]
    prose = " ".join(line for line in lines if line and not line.startswith("#"))
    prose = re.sub(r"\s+", " ", prose).strip()
    return prose[:max_chars]
