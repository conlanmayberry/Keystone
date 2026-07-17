from __future__ import annotations

from functools import lru_cache

from sklearn.feature_extraction.text import HashingVectorizer


@lru_cache(maxsize=4)
def _vectorizer(vector_dim: int) -> HashingVectorizer:
    # HashingVectorizer holds no fitted state, so one instance per
    # vector_dim is safe to share across every caller and thread —
    # constructing it per embed() call was pure overhead.
    return HashingVectorizer(n_features=vector_dim, alternate_sign=False, norm="l2")


def embed(text: str, vector_dim: int) -> list[float]:
    """Stateless, local, deterministic — no fitting, no persisted
    vectorizer state, no network. HashingVectorizer maps text to a
    fixed-size vector via hashed n-grams, so unlike TfidfVectorizer it
    needs no corpus-wide fit: safe to call from any process at any time,
    and a growing memory store never invalidates previously-stored
    vectors. norm="l2" means cosine similarity reduces to a plain dot
    product at query time (see memory/retrieval.py).
    """
    vector = _vectorizer(vector_dim).transform([text])
    return vector.toarray()[0].tolist()
