from __future__ import annotations

from typing import Any

from megachud.models.approval import RiskLevel
from megachud.obsidian.research import ResearchSynthesisError, ResearchSynthesizer
from megachud.obsidian.vault import VaultWriter
from megachud.tools.base import Tool, ToolResult, ToolValidationError


class WriteResearchNoteTool(Tool):
    """Registered only when an LLM client is configured (see api/app.py) —
    the whole tool is one LLM synthesis call, so there is nothing useful
    it can do without a key.

    MEDIUM risk, matching write_file: it writes a new file, and it writes
    it outside the workspace sandbox into the user's real vault. It never
    modifies an existing note (VaultWriter suffixes on collision) and never
    deletes anything, so it stays short of HIGH_IRREVERSIBLE.
    """

    name = "write_research_note"
    description = (
        "Synthesize research findings into a note written directly into the user's "
        "Obsidian vault, with [[wikilinks]] to related notes that already exist "
        "there. Use this when you have gathered something worth keeping — after "
        "web_search/http_fetch/extract_text, or after working something out. Pass "
        "the raw findings; the note is written for you. Only facts present in "
        "'findings' end up in the note."
    )
    risk_level = RiskLevel.MEDIUM

    def __init__(self, synthesizer: ResearchSynthesizer, vault_writer: VaultWriter, folder: str = "research") -> None:
        self._synthesizer = synthesizer
        self._vault_writer = vault_writer
        self._folder = folder

    def validate_args(self, args: dict[str, Any]) -> None:
        if not isinstance(args.get("topic"), str) or not args["topic"].strip():
            raise ToolValidationError("'topic' (non-empty str) is required")
        if not isinstance(args.get("findings"), str) or not args["findings"].strip():
            raise ToolValidationError("'findings' (non-empty str) is required")
        sources = args.get("sources")
        if sources is not None and not (
            isinstance(sources, list) and all(isinstance(source, str) for source in sources)
        ):
            raise ToolValidationError("'sources', if given, must be a list of strings")

    def run(self, args: dict[str, Any]) -> ToolResult:
        self.validate_args(args)
        sources = list(args.get("sources") or [])

        try:
            note = self._synthesizer.synthesize(
                topic=args["topic"], findings=args["findings"], sources=sources
            )
        except ResearchSynthesisError as exc:
            # Nothing was written — a failed synthesis must never leave a
            # partial or templated note behind in a personal vault.
            return ToolResult(success=False, output="", error=f"research synthesis failed: {exc}")

        relative = self._vault_writer.write_research_note(
            note, folder=self._folder, sources=sources
        )
        linked = [linked_note.title for linked_note in note.linked_notes]
        link_summary = ", ".join(linked) if linked else "no existing notes"
        return ToolResult(
            success=True,
            output=f"wrote vault note {relative.as_posix()!r} ({note.title}); linked to {link_summary}",
            metadata={
                "path": relative.as_posix(),
                "title": note.title,
                "linked_notes": linked,
                "tags": note.tags,
                "tokens_input": note.tokens_input,
                "tokens_output": note.tokens_output,
                "model": note.model,
            },
        )
