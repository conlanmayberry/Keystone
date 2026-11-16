from __future__ import annotations

from dataclasses import dataclass, field

from megachud.events.logger import EventLogger
from megachud.llm.client import LLMClient, LLMError
from megachud.obsidian.guidance import GuidanceLoader, with_guidance
from megachud.obsidian.index import VaultIndex, VaultNote
from megachud.routing.engine import ModelProfile, compute_cost_usd, profile_by_name
from megachud.runtime.thoughts import ThoughtLog


class ResearchSynthesisError(Exception):
    """Raised when the LLM call fails or returns something unusable.

    Unlike every other LLM swap-point in this codebase, there is
    deliberately NO deterministic fallback here. The other consumers
    degrade to a template because a mediocre reflection is still better
    than no reflection, and it lands in MegaChud's own database. This one
    writes a permanent file into the user's personal Obsidian vault, where
    a template-generated stub is worse than nothing: it can't be told
    apart from a real note at a glance, and cleaning it up is manual work.
    Failing loudly and writing nothing is the correct degradation.
    """


@dataclass
class ResearchNote:
    title: str
    summary: str
    body_markdown: str
    tags: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    # Populated by the synthesizer after link resolution — only ever
    # contains notes that were verified to exist in the vault.
    linked_notes: list[VaultNote] = field(default_factory=list)
    tokens_input: int = 0
    tokens_output: int = 0
    model: str | None = None


_TOOL_SCHEMA = {
    "name": "submit_research_note",
    "description": "Submit a synthesized research note for the user's Obsidian vault.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short human title for the note. Becomes the filename.",
            },
            "summary": {
                "type": "string",
                "description": "One or two sentences capturing the finding. Shown in frontmatter.",
            },
            "body_markdown": {
                "type": "string",
                "description": (
                    "The full note body in Markdown. Use [[Note Title]] wikilinks inline, "
                    "in the sentence where the connection is actually made, using EXACT "
                    "titles from the existing-notes list you were given."
                ),
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Lowercase, hyphenated topic tags. No leading '#'.",
            },
            "open_questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "What this research did not settle. Empty list is fine.",
            },
        },
        "required": ["title", "summary", "body_markdown", "tags", "open_questions"],
    },
}

_SYSTEM_PROMPT = (
    "You write research notes directly into a human's personal Obsidian vault. "
    "Synthesize the findings you are given into one focused, well-structured "
    "Markdown note that reads like something a thoughtful person wrote for their "
    "own future reference — not a report, not a summary of a summary.\n"
    "\n"
    "Grounding rules, in order of importance:\n"
    "1. Every factual claim must come from the findings given to you. Never add "
    "outside facts, statistics, dates, or citations from your own knowledge. If "
    "the findings are thin, write a short note; do not pad it.\n"
    "2. You will be given a list of notes that ALREADY EXIST in this vault. Link "
    "to them with [[Exact Title]] wikilinks, placed inline in the sentence that "
    "actually makes the connection. Never link to a title that is not on that "
    "list — an invented wikilink creates a broken placeholder note in the user's "
    "vault.\n"
    "3. Only link where there is a real conceptual connection, and say what the "
    "connection IS. A link with no stated relationship is noise. Zero links is a "
    "valid and correct outcome when nothing in the vault relates.\n"
    "4. Do not write a title heading (# ...) — the note's filename is the title. "
    "Start with prose or a '##' section heading.\n"
    "5. Do not write a 'Sources', 'References', 'Open questions', or 'Links' "
    "section in the body. All four are appended automatically — 'Sources' and "
    "'Links' from the data you were given, 'Open questions' from the "
    "open_questions field. Writing your own duplicates them in the file. Put "
    "unresolved questions in open_questions, not in the body."
)



class ResearchSynthesizer:
    """Turns raw findings into a vault-ready note in one LLM call.

    Direct synthesis: the model writes the note body itself, rather than
    filling slots in a template. The only post-processing is link
    validation (see VaultIndex.resolve_links) — the prose is the model's.
    """

    def __init__(
        self,
        client: LLMClient,
        index: VaultIndex,
        *,
        model: str,
        max_tokens: int,
        link_candidates: int = 12,
        guidance_loader: GuidanceLoader | None = None,
        profiles: list[ModelProfile] | None = None,
        event_logger: EventLogger | None = None,
        thought_log: ThoughtLog | None = None,
    ) -> None:
        self._client = client
        self._index = index
        self._model = model
        self._max_tokens = max_tokens
        self._link_candidates = link_candidates
        self._guidance_loader = guidance_loader
        self._profiles = profiles or []
        self._event_logger = event_logger
        self._thought_log = thought_log

    def _system_prompt(self) -> str:
        """Rebuilt per call, not cached at construction: the point of
        vault-held guidance is that editing a note in Obsidian changes
        behavior on the next run with no restart.
        """
        guidance = self._guidance_loader.load("research") if self._guidance_loader is not None else ""
        return with_guidance(_SYSTEM_PROMPT, guidance)

    def synthesize(
        self,
        *,
        topic: str,
        findings: str,
        sources: list[str] | None = None,
        task_id: str | None = None,
    ) -> ResearchNote:
        candidates = self._index.relevant(f"{topic}\n{findings}", self._link_candidates)

        try:
            response = self._client.complete(
                model=self._model,
                system=self._system_prompt(),
                messages=[
                    {"role": "user", "content": self._build_prompt(topic, findings, sources or [], candidates)}
                ],
                max_tokens=self._max_tokens,
                tool=_TOOL_SCHEMA,
            )
        except LLMError as exc:
            raise ResearchSynthesisError(f"LLM call failed: {exc}") from exc

        if not response.raw_tool_calls:
            raise ResearchSynthesisError("model returned no tool call — nothing to write")

        try:
            data = response.raw_tool_calls[0]["input"]
            title = str(data["title"]).strip()
            body = str(data["body_markdown"])
            note = ResearchNote(
                title=title,
                summary=str(data["summary"]).strip(),
                body_markdown=body,
                tags=[str(tag).lstrip("#").strip() for tag in data["tags"] if str(tag).strip()],
                open_questions=[str(q).strip() for q in data["open_questions"] if str(q).strip()],
                tokens_input=response.tokens_input,
                tokens_output=response.tokens_output,
                model=response.model,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ResearchSynthesisError(f"malformed tool input: {exc}") from exc

        if not note.title:
            raise ResearchSynthesisError("model returned an empty title — no filename to write to")

        note.body_markdown, note.linked_notes = self._index.resolve_links(note.body_markdown, candidates)

        self._log_cost(task_id, response.model, response.tokens_input, response.tokens_output)
        if self._thought_log is not None:
            self._thought_log.record(
                "research",
                f"Wrote vault note '{note.title}', linked to {len(note.linked_notes)} existing note(s).",
            )
        return note

    def _build_prompt(
        self, topic: str, findings: str, sources: list[str], candidates: list[VaultNote]
    ) -> str:
        lines = [f"Research topic: {topic}", "", "Findings to synthesize:", findings]
        if sources:
            lines += ["", "Sources these findings came from:"]
            lines += [f"  - {source}" for source in sources]

        lines += ["", "Notes that already exist in this vault (link only to these, by exact title):"]
        if candidates:
            for note in candidates:
                excerpt = note.excerpt or "(empty note)"
                lines.append(f"  - {note.title} — {excerpt}")
        else:
            lines.append("  (none related — write the note with no wikilinks)")
        return "\n".join(lines)

    def _log_cost(self, task_id: str | None, model: str, tokens_input: int, tokens_output: int) -> None:
        if self._event_logger is None:
            return
        profile = profile_by_name(self._profiles, model)
        cost_usd = compute_cost_usd(profile, tokens_input, tokens_output) if profile is not None else None
        self._event_logger.log(
            event_type="llm_call",
            task_id=task_id,
            tool_name="llm:research",
            cost_usd=cost_usd,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            payload={"model": model, "consumer": "research"},
        )
