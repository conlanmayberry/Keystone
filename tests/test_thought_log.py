from __future__ import annotations

from megachud.runtime.thoughts import ThoughtLog


def test_records_newest_first():
    log = ThoughtLog(max_entries=10, max_chars=100)
    log.record("planner", "first")
    log.record("conversation", "second")
    recent = log.recent()
    assert [t["text"] for t in recent] == ["second", "first"]
    assert recent[0]["source"] == "conversation"
    assert "ts" in recent[0]


def test_max_entries_evicts_oldest():
    log = ThoughtLog(max_entries=3, max_chars=100)
    for i in range(5):
        log.record("s", f"thought {i}")
    recent = log.recent()
    assert len(recent) == 3
    assert [t["text"] for t in recent] == ["thought 4", "thought 3", "thought 2"]


def test_truncates_long_text():
    log = ThoughtLog(max_entries=10, max_chars=10)
    log.record("s", "this is a very long thought that exceeds the cap")
    text = log.recent()[0]["text"]
    assert len(text) == 10
    assert text.endswith("…")


def test_ignores_empty_text():
    log = ThoughtLog(max_entries=10, max_chars=100)
    log.record("s", "")
    log.record("s", "   ")
    assert log.recent() == []
