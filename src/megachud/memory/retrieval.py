from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from sqlalchemy.orm import Session, sessionmaker

from megachud.memory.vectorizer import embed
from megachud.models.memory_entry import MemoryEntry, MemoryType


@dataclass
class ScoredMemoryEntry:
    entry: MemoryEntry
    score: float


def search(
    session_factory: sessionmaker[Session],
    query_text: str,
    vector_dim: int,
    memory_type: MemoryType | None = None,
    top_k: int = 5,
) -> list[ScoredMemoryEntry]:
    """Load candidate (id, embedding) pairs only — never the full rows —
    stack embeddings into one (N, vector_dim) matrix, embed query_text
    once, and score with a single vectorized matmul; only the top_k
    winners are then fetched as full MemoryEntry rows. Since embeddings
    are L2-normalized (HashingVectorizer norm="l2"), the dot product equals
    cosine similarity. Bumps access_count/last_accessed_at on returned rows
    — real use of the aging columns. This is the clean query interface a
    future Context Builder will consume.
    """
    session = session_factory()
    try:
        query = session.query(MemoryEntry.id, MemoryEntry.embedding_json)
        if memory_type is not None:
            query = query.filter_by(memory_type=memory_type)
        candidates = query.all()

        if not candidates:
            return []

        matrix = np.array([json.loads(embedding_json) for _, embedding_json in candidates], dtype=np.float32)
        query_vec = np.array(embed(query_text, vector_dim), dtype=np.float32)
        scores = matrix @ query_vec

        # argpartition is O(N) vs argsort's O(N log N); only the top_k
        # slice then needs an actual sort.
        if len(scores) > top_k:
            partitioned = np.argpartition(-scores, top_k)[:top_k]
            ranked_idx = partitioned[np.argsort(-scores[partitioned])]
        else:
            ranked_idx = np.argsort(-scores)

        top_ids = [candidates[int(i)][0] for i in ranked_idx]
        entries_by_id = {
            entry.id: entry
            for entry in session.query(MemoryEntry).filter(MemoryEntry.id.in_(top_ids)).all()
        }

        now = datetime.now(timezone.utc)
        results: list[ScoredMemoryEntry] = []
        for idx in ranked_idx:
            i = int(idx)
            entry = entries_by_id[candidates[i][0]]
            entry.access_count += 1
            entry.last_accessed_at = now
            results.append(ScoredMemoryEntry(entry=entry, score=float(scores[i])))

        session.commit()
        for result in results:
            session.expunge(result.entry)
        return results
    finally:
        session.close()
