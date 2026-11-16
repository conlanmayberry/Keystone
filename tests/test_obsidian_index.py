from __future__ import annotations

from megachud.obsidian.index import VaultIndex

VECTOR_DIM = 64


def write(vault, relative: str, text: str) -> None:
    path = vault / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_scan_prefers_h1_over_filename_for_title(tmp_vault):
    write(tmp_vault, "084a4be0.md", "---\ntype: semantic\n---\n\n# Lesson: retries need backoff\n\nBody text here.")
    index = VaultIndex(tmp_vault, VECTOR_DIM)

    notes = index.scan()

    assert len(notes) == 1
    assert notes[0].title == "Lesson: retries need backoff"
    assert notes[0].link_target == "084a4be0"
    assert "Body text here." in notes[0].excerpt


def test_scan_falls_back_to_filename_when_no_heading(tmp_vault):
    write(tmp_vault, "Deep Work.md", "Some thoughts on focus.")
    index = VaultIndex(tmp_vault, VECTOR_DIM)

    assert index.scan()[0].title == "Deep Work"


def test_frontmatter_title_wins(tmp_vault):
    write(tmp_vault, "note.md", "---\ntitle: Real Title\n---\n\n# Heading\n\nbody")
    assert VaultIndex(tmp_vault, VECTOR_DIM).scan()[0].title == "Real Title"


def test_duplicate_stems_get_full_path_link_targets(tmp_vault):
    write(tmp_vault, "a/Notes.md", "one")
    write(tmp_vault, "b/Notes.md", "two")
    write(tmp_vault, "Unique.md", "three")

    targets = {note.link_target for note in VaultIndex(tmp_vault, VECTOR_DIM).scan()}

    assert targets == {"a/Notes", "b/Notes", "Unique"}


def test_dot_directories_are_skipped(tmp_vault):
    write(tmp_vault, ".obsidian/plugins/thing.md", "config junk")
    write(tmp_vault, ".trash/deleted.md", "deleted note")
    write(tmp_vault, "Real.md", "real note")

    notes = VaultIndex(tmp_vault, VECTOR_DIM).scan()

    assert [note.title for note in notes] == ["Real"]


def test_relevant_ranks_related_notes_first(tmp_vault):
    write(tmp_vault, "Sourdough.md", "sourdough starter hydration and bulk fermentation")
    write(tmp_vault, "Taxes.md", "quarterly estimated tax payments and deductions")
    index = VaultIndex(tmp_vault, VECTOR_DIM)

    results = index.relevant("bulk fermentation of sourdough", top_k=2)

    assert results[0].title == "Sourdough"


def test_relevant_excludes_zero_similarity_notes(tmp_vault):
    write(tmp_vault, "Sourdough.md", "sourdough starter hydration")
    index = VaultIndex(tmp_vault, VECTOR_DIM)

    # No shared terms at all -> a link here would be a fabricated connection.
    assert index.relevant("zzzqqq unrelated gibberish", top_k=5) == []


def test_relevant_on_missing_vault_root_is_empty(tmp_path):
    index = VaultIndex(tmp_path / "does-not-exist", VECTOR_DIM)

    assert index.scan() == []
    assert index.relevant("anything", top_k=5) == []


def test_resolve_links_rewrites_title_to_filename_with_alias(tmp_vault):
    write(tmp_vault, "084a4be0.md", "# Lesson: retries need backoff\n\nbody")
    index = VaultIndex(tmp_vault, VECTOR_DIM)
    candidates = index.scan()

    body, linked = index.resolve_links("See [[Lesson: retries need backoff]] for context.", candidates)

    assert body == "See [[084a4be0|Lesson: retries need backoff]] for context."
    assert [note.link_target for note in linked] == ["084a4be0"]


def test_resolve_links_leaves_plain_link_when_title_matches_filename(tmp_vault):
    write(tmp_vault, "Deep Work.md", "focus")
    index = VaultIndex(tmp_vault, VECTOR_DIM)

    body, linked = index.resolve_links("Related: [[Deep Work]].", index.scan())

    assert body == "Related: [[Deep Work]]."
    assert len(linked) == 1


def test_resolve_links_strips_hallucinated_links(tmp_vault):
    write(tmp_vault, "Deep Work.md", "focus")
    index = VaultIndex(tmp_vault, VECTOR_DIM)

    body, linked = index.resolve_links(
        "Compare [[Deep Work]] with [[A Note That Does Not Exist]].", index.scan()
    )

    # The bogus one degrades to plain text rather than creating a broken
    # placeholder note in the vault.
    assert body == "Compare [[Deep Work]] with A Note That Does Not Exist."
    assert [note.title for note in linked] == ["Deep Work"]


def test_resolve_links_preserves_model_supplied_alias(tmp_vault):
    write(tmp_vault, "084a4be0.md", "# Lesson: retries\n\nbody")
    index = VaultIndex(tmp_vault, VECTOR_DIM)

    body, _ = index.resolve_links("As in [[Lesson: retries|that earlier lesson]].", index.scan())

    assert body == "As in [[084a4be0|that earlier lesson]]."


def test_resolve_links_deduplicates_repeated_links(tmp_vault):
    write(tmp_vault, "Deep Work.md", "focus")
    index = VaultIndex(tmp_vault, VECTOR_DIM)

    _, linked = index.resolve_links("[[Deep Work]] and again [[Deep Work]].", index.scan())

    assert len(linked) == 1


def test_scan_reuses_cache_until_mtime_changes(tmp_vault):
    path = tmp_vault / "Note.md"
    path.write_text("# First\n\nbody", encoding="utf-8")
    index = VaultIndex(tmp_vault, VECTOR_DIM)
    assert index.scan()[0].title == "First"

    import os
    import time

    path.write_text("# Second\n\nbody", encoding="utf-8")
    # Force a distinct mtime — a same-second rewrite can otherwise land on
    # the cached value on coarse-resolution filesystems.
    os.utime(path, (time.time() + 2, time.time() + 2))

    assert index.scan()[0].title == "Second"
