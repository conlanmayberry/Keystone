from __future__ import annotations

import os
import time

import pytest

from megachud.config import ResearchConfig
from megachud.llm.client import LLMResponse
from megachud.obsidian.guidance import GuidanceLoader
from megachud.obsidian.index import VaultIndex
from megachud.obsidian.research import ResearchSynthesizer
from tests.fixtures.fake_llm_client import FakeLLMClient

VECTOR_DIM = 64


def write_guidance(vault, name: str, text: str) -> None:
    folder = vault / "guidance"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


def test_missing_folder_loads_empty(tmp_vault):
    assert GuidanceLoader(tmp_vault).load() == ""


def test_empty_folder_loads_empty(tmp_vault):
    (tmp_vault / "guidance").mkdir()

    assert GuidanceLoader(tmp_vault).load() == ""


def test_notes_are_concatenated_under_their_filenames(tmp_vault):
    write_guidance(tmp_vault, "Alpha.md", "first rule")
    write_guidance(tmp_vault, "Beta.md", "second rule")

    loaded = GuidanceLoader(tmp_vault).load()

    assert loaded == "## Alpha\nfirst rule\n\n## Beta\nsecond rule"


def test_frontmatter_is_stripped(tmp_vault):
    write_guidance(tmp_vault, "Rules.md", "---\ntags: [guidance]\n---\n\nthe actual rule")

    loaded = GuidanceLoader(tmp_vault).load()

    assert "tags" not in loaded
    assert "the actual rule" in loaded


def test_max_chars_truncates_at_a_note_boundary(tmp_vault):
    write_guidance(tmp_vault, "Alpha.md", "a" * 200)
    write_guidance(tmp_vault, "Beta.md", "b" * 200)

    loaded = GuidanceLoader(tmp_vault, max_chars=250).load()

    # Beta is dropped whole — half a rule read as a whole rule is worse
    # than the rule being absent.
    assert "## Alpha" in loaded
    assert "## Beta" not in loaded


def test_order_frontmatter_overrides_alphabetical_order(tmp_vault):
    write_guidance(tmp_vault, "Zulu.md", "---\norder: 1\n---\n\nfirst")
    write_guidance(tmp_vault, "Alpha.md", "---\norder: 2\n---\n\nsecond")

    loaded = GuidanceLoader(tmp_vault).load()

    assert loaded.index("## Zulu") < loaded.index("## Alpha")


def test_budget_drops_the_lowest_priority_note_not_the_last_alphabetically(tmp_vault):
    write_guidance(tmp_vault, "Alpha.md", "---\norder: 9\n---\n\n" + "a" * 200)
    write_guidance(tmp_vault, "Zulu.md", "---\norder: 1\n---\n\n" + "z" * 200)

    loaded = GuidanceLoader(tmp_vault, max_chars=250).load()

    # This is the whole point of `order:` — without it, the important note
    # is dropped purely because its filename sorts late.
    assert "## Zulu" in loaded
    assert "## Alpha" not in loaded


def test_unordered_notes_sort_after_ordered_ones(tmp_vault):
    write_guidance(tmp_vault, "Alpha.md", "no order key")
    write_guidance(tmp_vault, "Zulu.md", "---\norder: 5\n---\n\nordered")

    loaded = GuidanceLoader(tmp_vault).load()

    # Adding a note without `order:` must never displace one the user
    # deliberately prioritized.
    assert loaded.index("## Zulu") < loaded.index("## Alpha")


def test_malformed_order_value_does_not_break_loading(tmp_vault):
    write_guidance(tmp_vault, "Bad.md", "---\norder: not-a-number\n---\n\nstill loaded")

    assert "still loaded" in GuidanceLoader(tmp_vault).load()


def test_applies_to_scopes_a_note_to_its_consumers(tmp_vault):
    write_guidance(tmp_vault, "Linking.md", "---\napplies_to: [research]\n---\n\nlinking rule")
    write_guidance(tmp_vault, "Planning.md", "---\napplies_to: [planner]\n---\n\nplanning rule")
    loader = GuidanceLoader(tmp_vault)

    assert "linking rule" in loader.load("research")
    assert "planning rule" not in loader.load("research")
    assert "planning rule" in loader.load("planner")
    assert "linking rule" not in loader.load("planner")


def test_note_without_applies_to_reaches_every_consumer(tmp_vault):
    write_guidance(tmp_vault, "Universal.md", "read the error first")
    loader = GuidanceLoader(tmp_vault)

    for consumer in ("research", "planner", "conversation"):
        assert "read the error first" in loader.load(consumer)


def test_load_without_a_consumer_returns_everything(tmp_vault):
    write_guidance(tmp_vault, "Scoped.md", "---\napplies_to: [planner]\n---\n\nplanner only")

    assert "planner only" in GuidanceLoader(tmp_vault).load()


def test_applies_to_matching_is_case_insensitive(tmp_vault):
    write_guidance(tmp_vault, "Scoped.md", "---\napplies_to: [Planner]\n---\n\nrule")

    assert "rule" in GuidanceLoader(tmp_vault).load("PLANNER")


def test_malformed_applies_to_falls_back_to_applying_everywhere(tmp_vault):
    # A broken scope must not silently hide the note — failing open is
    # right here, since the cost is a note in the wrong prompt rather than
    # a rule silently not applying.
    write_guidance(tmp_vault, "Bad.md", "---\napplies_to: not-a-list\n---\n\nstill applies")

    assert "still applies" in GuidanceLoader(tmp_vault).load("planner")


def test_max_notes_caps_the_count(tmp_vault):
    for i in range(5):
        write_guidance(tmp_vault, f"Note{i}.md", f"rule {i}")

    loaded = GuidanceLoader(tmp_vault, max_notes=2).load()

    assert loaded.count("##") == 2


def test_edits_are_picked_up_without_restart(tmp_vault):
    write_guidance(tmp_vault, "Rules.md", "original rule")
    loader = GuidanceLoader(tmp_vault)
    assert "original rule" in loader.load()

    path = tmp_vault / "guidance" / "Rules.md"
    path.write_text("revised rule", encoding="utf-8")
    os.utime(path, (time.time() + 2, time.time() + 2))

    assert "revised rule" in loader.load()


def test_only_the_guidance_folder_is_read(tmp_vault):
    write_guidance(tmp_vault, "Rules.md", "real guidance")
    (tmp_vault / "research").mkdir()
    (tmp_vault / "research" / "Note.md").write_text("agent-written note", encoding="utf-8")

    loaded = GuidanceLoader(tmp_vault).load()

    assert "agent-written note" not in loaded


def test_guidance_reaches_the_synthesis_system_prompt(tmp_vault):
    write_guidance(tmp_vault, "Rules.md", "Always prefer primary sources.")
    client = FakeLLMClient(
        response=LLMResponse(
            text="", tokens_input=1, tokens_output=1, model="m", stop_reason="tool_use",
            raw_tool_calls=[{
                "name": "submit_research_note",
                "input": {
                    "title": "T", "summary": "S", "body_markdown": "B",
                    "tags": [], "open_questions": [],
                },
            }],
        )
    )
    synthesizer = ResearchSynthesizer(
        client,
        VaultIndex(tmp_vault, VECTOR_DIM),
        model="m",
        max_tokens=512,
        guidance_loader=GuidanceLoader(tmp_vault),
    )

    synthesizer.synthesize(topic="t", findings="f")

    system = client.calls[0]["system"]
    assert "Always prefer primary sources." in system
    # The grounding rules stay above the user's guidance and are declared
    # non-overridable by it.
    assert system.index("Never add outside facts") < system.index("Always prefer primary sources.")
    assert "the rules above win" in system


def test_no_guidance_leaves_the_base_prompt_untouched(tmp_vault):
    loader = GuidanceLoader(tmp_vault)
    client = FakeLLMClient(
        response=LLMResponse(
            text="", tokens_input=1, tokens_output=1, model="m", stop_reason="tool_use",
            raw_tool_calls=[{
                "name": "submit_research_note",
                "input": {
                    "title": "T", "summary": "S", "body_markdown": "B",
                    "tags": [], "open_questions": [],
                },
            }],
        )
    )
    synthesizer = ResearchSynthesizer(
        client, VaultIndex(tmp_vault, VECTOR_DIM), model="m", max_tokens=512, guidance_loader=loader
    )

    synthesizer.synthesize(topic="t", findings="f")

    assert "the rules above win" not in client.calls[0]["system"]


def test_guidance_folder_is_not_offered_as_link_candidates(tmp_vault):
    write_guidance(tmp_vault, "Research Method.md", "how to research things properly")
    (tmp_vault / "Sourdough.md").write_text("how to research sourdough properly", encoding="utf-8")

    index = VaultIndex(tmp_vault, VECTOR_DIM, exclude_folders=("guidance",))

    assert [note.title for note in index.scan()] == ["Sourdough"]


def test_config_rejects_writing_into_the_guidance_folder():
    # The agent reads its instructions from guidance_folder, so being able
    # to write there would let it rewrite its own instructions.
    with pytest.raises(ValueError, match="must differ"):
        ResearchConfig(folder="guidance", guidance_folder="guidance")


def test_config_allows_distinct_folders():
    config = ResearchConfig(folder="research", guidance_folder="guidance")

    assert config.folder == "research"
