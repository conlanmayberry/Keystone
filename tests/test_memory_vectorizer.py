from __future__ import annotations

import math

from megachud.memory.vectorizer import embed


def test_same_text_produces_same_vector():
    a = embed("write a python script", 256)
    b = embed("write a python script", 256)
    assert a == b


def test_different_text_produces_different_vector():
    a = embed("write a python script", 256)
    b = embed("bake a chocolate cake", 256)
    assert a != b


def test_vector_has_configured_dimension():
    vec = embed("hello world", 128)
    assert len(vec) == 128


def test_vector_is_unit_norm():
    vec = embed("some reasonably long piece of text to embed", 256)
    norm = math.sqrt(sum(v * v for v in vec))
    assert math.isclose(norm, 1.0, abs_tol=1e-6)


def test_empty_text_does_not_raise():
    vec = embed("", 64)
    assert len(vec) == 64
