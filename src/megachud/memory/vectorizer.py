from __future__ import annotations

from sklearn.feature_extraction.text import HashingVectorizer


def embed(text: str, vector_dim: int) -> list[float]:
    """Stateless, local, deterministic — no fitting, no persisted
    vectorizer state, no network. HashingVectorizer maps text to a
    fixed-size vector via hashed n-grams, so unlike TfidfVectorizer it
    needs no corpus-wide fit: safe to call from any process at any time,
    and a growing memory store never invalidates previously-stored
    vectors. norm="l2" means cosine similarity reduces to a plain dot
    product at query time (see memory/retrieval.py).
    """
    vectorizer = HashingVectorizer(n_features=vector_dim, alternate_sign=False, norm="l2")
    vector = vectorizer.transform([text])
    return vector.toarray()[0].tolist()
