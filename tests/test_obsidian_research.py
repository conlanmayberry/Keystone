from __future__ import annotations

import pytest
import yaml

from megachud.llm.client import LLMRequestError, LLMResponse
from megachud.obsidian.index import VaultIndex
from megachud.obsidian.research import ResearchSynthesisError, ResearchSynthesizer
from megachud.obsidian.vault import VaultWriter
from tests.fixtures.fake_llm_client import FakeLLMClient

VECTOR_DIM = 64


def note_response(**overrides) -> LLMResponse:
    payload = {
        "title": "Bulk fermentation timing",
        "summary": "Warmer dough ferments faster; watch volume, not the clock.",
        "body_markdown": "Volume gain beats elapsed time. This refines [[Sourdough]].",
        "tags": ["#baking", "sourdough"],
        "open_questions": ["Does this hold below 18C?"],
    }
    payload.update(overrides)
    return LLMResponse(
        text="",
        tokens_input=120,
        tokens_output=300,
        model="claude-sonnet-5",
        stop_reason="tool_use",
        raw_tool_calls=[{"name": "submit_research_note", "input": payload}],
    )


def build(tmp_vault, response=None, error=None) -> tuple[ResearchSynthesizer, FakeLLMClient]:
    (tmp_vault / "Sourdough.md").write_text("sourdough starter hydration and bulk fermentation", encoding="utf-8")
    client = FakeLLMClient(response=response, error=error)
    index = VaultIndex(tmp_vault, VECTOR_DIM)
    synthesizer = ResearchSynthesizer(client, index, model="claude-sonnet-5", max_tokens=2048)
    return synthesizer, client


def test_synthesize_returns_llm_written_body_with_resolved_links(tmp_vault):
    synthesizer, _ = build(tmp_vault, response=note_response())

    note = synthesizer.synthesize(topic="bulk fermentation", findings="Dough at 26C doubled in 4 hours.")

    assert note.title == "Bulk fermentation timing"
    # The body is the model's prose, passed through untouched apart from links.
    assert note.body_markdown == "Volume gain beats elapsed time. This refines [[Sourdough]]."
    assert [linked.title for linked in note.linked_notes] == ["Sourdough"]
    assert note.tags == ["baking", "sourdough"]  # leading '#' stripped
    assert note.tokens_input == 120


def test_prompt_forbids_body_sections_the_template_already_appends(tmp_vault):
    # A live run produced a note with two "Open questions" sections: one
    # written in the body, one rendered from the structured field.
    synthesizer, client = build(tmp_vault, response=note_response())

    synthesizer.synthesize(topic="t", findings="f")

    system = client.calls[0]["system"]
    for section in ("Sources", "References", "Open questions", "Links"):
        assert section in system
    assert "appended automatically" in system


def test_prompt_offers_only_real_vault_notes_as_link_candidates(tmp_vault):
    synthesizer, client = build(tmp_vault, response=note_response())

    synthesizer.synthesize(topic="bulk fermentation sourdough", findings="hydration notes")

    prompt = client.calls[0]["messages"][0]["content"]
    assert "Notes that already exist in this vault" in prompt
    assert "Sourdough" in prompt
    assert client.calls[0]["tool"]["name"] == "submit_research_note"


def test_hallucinated_link_is_stripped_from_body(tmp_vault):
    synthesizer, _ = build(
        tmp_vault,
        response=note_response(body_markdown="Builds on [[Sourdough]] and [[Imaginary Note]]."),
    )

    note = synthesizer.synthesize(topic="bulk fermentation", findings="f")

    assert note.body_markdown == "Builds on [[Sourdough]] and Imaginary Note."
    assert [linked.title for linked in note.linked_notes] == ["Sourdough"]


def test_llm_error_raises_rather_than_writing_a_template(tmp_vault):
    synthesizer, _ = build(tmp_vault, error=LLMRequestError("boom", retryable=True))

    with pytest.raises(ResearchSynthesisError):
        synthesizer.synthesize(topic="t", findings="f")


def test_no_tool_call_raises(tmp_vault):
    response = LLMResponse(text="I'd rather not", tokens_input=5, tokens_output=5, model="m", stop_reason="end_turn")
    synthesizer, _ = build(tmp_vault, response=response)

    with pytest.raises(ResearchSynthesisError):
        synthesizer.synthesize(topic="t", findings="f")


def test_malformed_tool_input_raises(tmp_vault):
    response = LLMResponse(
        text="", tokens_input=5, tokens_output=5, model="m", stop_reason="tool_use",
        raw_tool_calls=[{"name": "submit_research_note", "input": {"title": "only this"}}],
    )
    synthesizer, _ = build(tmp_vault, response=response)

    with pytest.raises(ResearchSynthesisError):
        synthesizer.synthesize(topic="t", findings="f")


def test_empty_title_raises(tmp_vault):
    synthesizer, _ = build(tmp_vault, response=note_response(title="   "))

    with pytest.raises(ResearchSynthesisError):
        synthesizer.synthesize(topic="t", findings="f")


def test_written_note_has_frontmatter_links_and_sources(tmp_vault):
    synthesizer, _ = build(tmp_vault, response=note_response())
    note = synthesizer.synthesize(
        topic="bulk fermentation", findings="f", sources=["https://example.com/bread"]
    )

    relative = VaultWriter(tmp_vault).write_research_note(
        note, sources=["https://example.com/bread"]
    )
    text = (tmp_vault / relative).read_text(encoding="utf-8")

    assert relative.as_posix() == "research/Bulk fermentation timing.md"
    frontmatter = yaml.safe_load(text.split("---")[1])
    assert frontmatter["type"] == "research"
    assert frontmatter["tags"] == ["research", "baking", "sourdough"]
    assert frontmatter["source_urls"] == ["https://example.com/bread"]
    # No duplicate H1 — Obsidian titles the note from its filename.
    assert "# Bulk fermentation timing" not in text
    assert "[[Sourdough]]" in text
    assert "## Open questions" in text
    assert "https://example.com/bread" in text


def test_title_collision_does_not_overwrite_existing_note(tmp_vault):
    synthesizer, _ = build(tmp_vault, response=note_response())
    writer = VaultWriter(tmp_vault)
    note = synthesizer.synthesize(topic="t", findings="f")

    first = writer.write_research_note(note)
    second = writer.write_research_note(note)

    assert first.name == "Bulk fermentation timing.md"
    assert second.name == "Bulk fermentation timing 2.md"
    assert (tmp_vault / first).exists()


def test_unsafe_filename_characters_are_stripped(tmp_vault):
    synthesizer, _ = build(tmp_vault, response=note_response(title='Q3: profit/loss? <draft> [wip]'))
    note = synthesizer.synthesize(topic="t", findings="f")

    relative = VaultWriter(tmp_vault).write_research_note(note)

    assert relative.name == "Q3 profitloss draft wip.md"
    assert (tmp_vault / relative).exists()
