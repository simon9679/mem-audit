from __future__ import annotations

from dataclasses import dataclass

from mem_audit.connectors.mem0_connector import MemoryRecord
from mem_audit.embeddings import EmbedFn, iter_similar_pairs, top_k_neighbor_pairs

# Loose floor only — not a duplicate/contradiction decision boundary. See
# top_k_neighbor_pairs() in embeddings.py for why a fixed cosine threshold
# alone is the wrong tool here: OpenAI-family embeddings aren't reliably
# calibrated for absolute cutoffs. This value only skips pairs cheap enough
# to obviously not be worth an LLM call.
DEFAULT_MIN_SIMILARITY = 0.3
DEFAULT_TOP_K = 5

# Kept for people who explicitly want the old fixed-threshold behavior via
# find_duplicate_candidates(..., strategy="threshold"). Not the default.
DEFAULT_SIMILARITY_THRESHOLD = 0.75


@dataclass
class CandidatePair:
    record_a: MemoryRecord
    record_b: MemoryRecord
    similarity: float


def find_duplicate_candidates(
    records: list[MemoryRecord],
    embed_fn: EmbedFn,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    threshold: float | None = None,
) -> list[CandidatePair]:
    """
    Returns candidate pairs worth sending to the LLM judge. Cheap: one
    embedding call for all texts, then a chunked similarity scan that never
    materializes a full N x N matrix.

    Default strategy is top-k nearest neighbors (see embeddings.top_k_neighbor_pairs
    for why), not a fixed cosine threshold. Pass threshold=<float> explicitly
    to fall back to the old fixed-threshold behavior instead.
    """
    if len(records) < 2:
        return []

    texts = [r.text for r in records]
    vectors = embed_fn(texts)

    # Verified real risk: if embed_fn returns fewer/more vectors than
    # input texts (provider partial failure, silent truncation, batch
    # limit) the index-based zip of records[i]/records[j] to vectors[i]/
    # vectors[j] downstream silently misaligns — not a crash, wrong
    # candidate pairs with no indication anything went wrong. Fail loudly
    # instead of guessing.
    if vectors.shape[0] != len(texts):
        raise ValueError(
            f"embed_fn returned {vectors.shape[0]} vectors for {len(texts)} "
            f"input texts — provider likely truncated or partially failed "
            f"the batch. Refusing to continue with misaligned vectors."
        )

    pairs: list[CandidatePair] = []
    if threshold is not None:
        pair_iter = iter_similar_pairs(vectors, threshold=threshold)
    else:
        pair_iter = top_k_neighbor_pairs(vectors, k=top_k, min_similarity=min_similarity)

    for i, j, score in pair_iter:
        pairs.append(CandidatePair(record_a=records[i], record_b=records[j], similarity=score))
    return pairs
