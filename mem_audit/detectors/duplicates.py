from __future__ import annotations

from dataclasses import dataclass

from mem_audit.connectors.mem0_connector import MemoryRecord
from mem_audit.embeddings import EmbedFn, iter_similar_pairs, top_k_neighbor_pairs

# Verified real bug (not a guess): a confidence test with known ground
# truth found 3 real contradiction/update pairs scoring 0.27-0.29 cosine
# similarity — genuinely related facts phrased in very different
# vocabulary ("I don't have any pets" / "my dog needs to go to the vet").
# All 3 were correctly in top-k, and the judge correctly classified them
# when called directly — but a 0.3 floor silently dropped them before
# they ever reached the judge. Worse: unrelated pairs have scored as high
# as 0.22-0.26 in other tests, meaning "related" and "unrelated" ranges
# overlap around here — no floor value is safe. top-k already bounds LLM
# cost by pair count; a similarity floor on top of that doesn't add
# safety, it just risks re-introducing the same "guess a magic number"
# problem top-k was meant to avoid. Left non-zero only to skip the
# genuinely negative/near-zero end (numerically opposite embeddings).
DEFAULT_MIN_SIMILARITY = 0.05
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
