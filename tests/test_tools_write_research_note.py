from __future__ import annotations

import pytest

from megachud.llm.client import LLMRequestError, LLMResponse
from megachud.models.approval import RiskLevel
from megachud.obsidian.index import VaultIndex
from megachud.obsidian.research import ResearchSynthesizer
from megachud.obsidian.vault import VaultWriter
from megachud.tools.base import ToolValidationError
from megachud.tools.vault_tools import WriteResearchNoteTool
from tests.fixtures.fake_llm_client import FakeLLMClient

VECTOR_DIM = 64


def good_response() -> LLMResponse:
    return LLMResponse(
        text="", tokens_input=100, tokens_output=200, model="claude-sonnet-5", stop_reason="tool_use",
        raw_tool_calls=[{
            "name": "submit_research_note",
            "input": {
                "title": "Rate limit backoff",
                "summary": "Exponential backoff with jitter avoids thundering herds.",
                "body_markdown": "Jitter matters more than the base delay. See [[Retry Policy]].",
                "tags": ["reliability"],
                "open_questions": [],
            },
        }],
    )


def build_tool(tmp_vault, response=None, error=None) -> WriteResearchNoteTool:
    (tmp_vault / "Retry Policy.md").write_text(
        "backoff and jitter when retries hit a rate limit", encoding="utf-8"
    )
    index = VaultIndex(tmp_vault, VECTOR_DIM)
    synthesizer = ResearchSynthesizer(
        FakeLLMClient(response=response, error=error), index, model="claude-sonnet-5", max_tokens=1024
    )
    return WriteResearchNoteTool(synthesizer, VaultWriter(tmp_vault))


def test_tool_is_medium_risk():
    assert WriteResearchNoteTool.risk_level == RiskLevel.MEDIUM


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"topic": "t"},
        {"findings": "f"},
        {"topic": "", "findings": "f"},
        {"topic": "t", "findings": "   "},
        {"topic": "t", "findings": "f", "sources": "not-a-list"},
        {"topic": "t", "findings": "f", "sources": [1, 2]},
    ],
)
def test_validate_args_rejects_bad_input(tmp_vault, args):
    tool = build_tool(tmp_vault, response=good_response())

    with pytest.raises(ToolValidationError):
        tool.validate_args(args)


def test_run_writes_note_into_the_vault(tmp_vault):
    tool = build_tool(tmp_vault, response=good_response())

    result = tool.run(
        {
            "topic": "retry backoff",
            "findings": "Jitter spreads retries after a rate limit.",
            "sources": ["https://example.com/a"],
        }
    )

    assert result.success
    written = tmp_vault / "research" / "Rate limit backoff.md"
    assert written.exists()
    text = written.read_text(encoding="utf-8")
    assert "[[Retry Policy]]" in text
    assert "https://example.com/a" in text
    assert result.metadata["linked_notes"] == ["Retry Policy"]
    assert result.metadata["path"] == "research/Rate limit backoff.md"


def test_run_writes_nothing_when_synthesis_fails(tmp_vault):
    tool = build_tool(tmp_vault, error=LLMRequestError("down", retryable=True))

    result = tool.run({"topic": "t", "findings": "f"})

    assert not result.success
    assert "research synthesis failed" in result.error
    assert not (tmp_vault / "research").exists()
