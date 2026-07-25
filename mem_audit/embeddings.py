"""
Minimal embedding abstraction.

We deliberately don't reuse Mem0's own embedder config here: mem-audit must
keep working even against a Mem0 instance configured with an embedder the
auditor doesn't have credentials for (e.g. a self-hosted model). Users pass
their own embedding function; we ship an OpenAI-compatible default because
that's the lowest-friction option, but it's fully swappable.
"""
from __future__ import annotations

from typing import Callable, Iterator, Sequence

import numpy as np

EmbedFn = Callable[[Sequence[str]], np.ndarray]

# Provider-specific batching defaults. A single embeddings.create() over an
# entire memory store blows past real per-request limits — this is not
# hypothetical:
#   - OpenAI: max 8192 tokens per input, max 2048 array elements, and a hard
#     ~300k-token ceiling across the whole request (HTTP 400
#     "max_tokens_per_request" beyond it). We keep items well under 2048 and
#     tokens under 300k with headroom.
#   - GitHub Models: ~8K tokens per request — tighter still, so a much smaller
#     token budget and item cap.
# These are conservative on purpose (below the documented ceilings) so a batch
# never lands exactly on a limit.
_OPENAI_MAX_BATCH_TOKENS = 250_000
_OPENAI_MAX_BATCH_ITEMS = 128
_GITHUB_MAX_BATCH_TOKENS = 6_000
_GITHUB_MAX_BATCH_ITEMS = 64


TokenCounter = Callable[[str], int]


def _make_token_counter(model: str) -> TokenCounter:
    """
    Returns a callable(text) -> estimated token count.

    Uses tiktoken for an exact count when it's installed (optional extra:
    `pip install mem-audit[precise]`), falling back to a cheap len/4 heuristic
    otherwise. tiktoken must stay optional — the offline demo and CI run
    without it, so its absence can never break import or execution.
    """
    try:
        import tiktoken
    except ImportError:
        return lambda text: len(text) // 4 + 1

    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        # Unknown/provider-prefixed model id (e.g. "openai/text-embedding-3-small")
        # — cl100k_base is the right base encoding for the text-embedding-3-* family.
        encoding = tiktoken.get_encoding("cl100k_base")

    return lambda text: len(encoding.encode(text))


def _iter_batches(
    texts: Sequence[str],
    count_tokens: TokenCounter,
    max_batch_items: int,
    max_batch_tokens: int,
) -> Iterator[list[str]]:
    """
    Groups texts into batches that respect BOTH ceilings. A batch is closed
    (and the current text starts a new one) as soon as either adding the text
    would push the item count over max_batch_items or the running token
    estimate over max_batch_tokens.

    A single text whose own token estimate already exceeds max_batch_tokens
    still goes out in a batch by itself — we can't split it further here, and
    the per-input token limit is a separate concern from the per-request one.
    """
    batch: list[str] = []
    batch_tokens = 0
    for text in texts:
        text_tokens = count_tokens(text)
        if batch and (len(batch) >= max_batch_items or batch_tokens + text_tokens > max_batch_tokens):
            yield batch
            batch = []
            batch_tokens = 0
        batch.append(text)
        batch_tokens += text_tokens
    if batch:
        yield batch


def _embed_in_batches(
    client,
    model: str,
    texts: Sequence[str],
    count_tokens: TokenCounter,
    max_batch_items: int,
    max_batch_tokens: int,
) -> np.ndarray:
    """
    Embeds texts in provider-safe batches and stacks the results back into a
    single (len(texts), dim) matrix.

    The vector order must line up 1:1 with the input order — downstream code
    indexes records[i] <-> vectors[i], so any reordering silently corrupts
    the audit. We preserve order by concatenating batch results in the same
    order the batches were emitted (which follows input order).
    """
    if not texts:
        # Preserve the historical empty-input contract: a (0, 1536) matrix so
        # duplicates.py's shape check still passes on an empty store.
        return np.zeros((0, 1536))

    chunks: list[np.ndarray] = []
    for batch in _iter_batches(list(texts), count_tokens, max_batch_items, max_batch_tokens):
        resp = client.embeddings.create(model=model, input=batch)
        vectors = [item.embedding for item in resp.data]
        chunks.append(np.array(vectors, dtype=np.float32))

    return np.vstack(chunks)


def openai_embedder(
    model: str = "text-embedding-3-small",
    client=None,
    max_batch_tokens: int = _OPENAI_MAX_BATCH_TOKENS,
    max_batch_items: int = _OPENAI_MAX_BATCH_ITEMS,
) -> EmbedFn:
    """Returns an embed_fn backed by an OpenAI-compatible client.

    Texts are embedded in batches sized to stay under OpenAI's per-request
    limits (see the module-level constants); results are stacked back in
    input order.
    """
    if client is None:
        import openai

        client = openai.OpenAI()

    count_tokens = _make_token_counter(model)

    def embed(texts: Sequence[str]) -> np.ndarray:
        return _embed_in_batches(
            client, model, texts, count_tokens, max_batch_items, max_batch_tokens
        )

    return embed


def github_models_embedder(
    model: str = "openai/text-embedding-3-small",
    token: str | None = None,
    max_batch_tokens: int = _GITHUB_MAX_BATCH_TOKENS,
    max_batch_items: int = _GITHUB_MAX_BATCH_ITEMS,
) -> EmbedFn:
    """
    Embed_fn backed by GitHub Models' free OpenAI-compatible endpoint.

    Verified endpoint shape (docs.github.com/en/rest/models/embeddings,
    checked against current docs): base_url models.github.ai/inference,
    Bearer auth with a PAT that has `models: read`, model id prefixed with
    the provider ("openai/text-embedding-3-small"). This is a *free but
    rate-limited* route with a tight ~8K-token-per-request limit, so texts
    are embedded in small batches (see the module-level GitHub constants)
    rather than a single call — one call over a whole store would exceed the
    per-request quota on even a few dozen facts.

    token defaults to the GITHUB_TOKEN env var if not passed explicitly.
    """
    import os

    import openai

    resolved_token = token or os.environ.get("GITHUB_TOKEN")
    if not resolved_token:
        raise ValueError(
            "github_models_embedder requires a GitHub token — pass token= "
            "explicitly or set the GITHUB_TOKEN env var. The token needs "
            "the 'models: read' permission."
        )

    client = openai.OpenAI(base_url="https://models.github.ai/inference", api_key=resolved_token)
    count_tokens = _make_token_counter(model)

    def embed(texts: Sequence[str]) -> np.ndarray:
        return _embed_in_batches(
            client, model, texts, count_tokens, max_batch_items, max_batch_tokens
        )

    return embed


def cosine_similarity_matrix(vectors: np.ndarray) -> np.ndarray:
    """Pairwise cosine similarity, shape (n, n). Diagonal is ~1.0.

    Only safe for small n — materializes the full N×N matrix (e.g. ~400MB
    of float32 at n=10,000). Kept for tests and small stores; the audit
    pipeline uses iter_similar_pairs below for anything larger.
    """
    if vectors.shape[0] == 0:
        return np.zeros((0, 0))
    norm = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-8)
    return norm @ norm.T


def top_k_neighbor_pairs(vectors: np.ndarray, k: int = 5, min_similarity: float = 0.05, chunk_size: int = 512):
    """
    Yields (i, j, score) for every pair where j is among i's top-k nearest
    neighbors (or vice versa), without ever materializing the full N×N
    similarity matrix. Peak memory is O(chunk_size * n), same bound as
    iter_similar_pairs.

    Why top-k instead of a fixed cosine threshold: OpenAI-family embeddings
    are known to be poorly calibrated for absolute cosine cutoffs — the
    OpenAI community forum has reports of cosine similarity staying above
    ~0.68 even for genuinely unrelated texts, and "safe" thresholds used in
    practice vary roughly 0.75-0.87 depending on domain and model. There is
    no single correct number; picking one is a guess dressed up as a
    setting. Top-k sidesteps the guess: every memory gets compared against
    its k closest neighbors regardless of the absolute score, and the
    (comparatively cheap) LLM judge is what actually decides duplicate vs.
    contradiction vs. unrelated — not the embedding pass.

    min_similarity is a loose floor only (default 0.05), meant to skip
    only the near-zero/negative end. Confirmed via a ground-truth test
    that a 0.3 floor silently drops real pairs (0.27-0.29 cosine) —
    "related" and "unrelated" cosine ranges overlap around 0.22-0.29 for
    OpenAI-family embeddings, so any floor in that band risks false
    negatives. top-k is what actually bounds cost here, not this floor.

    Known limitation: chunking bounds peak memory, not time — this is
    still O(n^2) compute (every record's embedding is compared against
    every other's). Fine for hundreds-to-low-thousands of memories (a
    realistic personal memory store); would need a real ANN index (FAISS,
    HNSW, or the vector store's own similarity search) for tens of
    thousands of records. Not implemented — no one has hit this yet.
    """
    n = vectors.shape[0]
    if n < 2:
        return
    norm = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-8)
    effective_k = min(k, n - 1)

    best: dict[tuple[int, int], float] = {}
    for start in range(0, n, chunk_size):
        end = min(start + chunk_size, n)
        chunk = norm[start:end]           # (chunk_len, d)
        sims = chunk @ norm.T             # (chunk_len, n) — full row per record in this chunk
        for local_i in range(sims.shape[0]):
            i = start + local_i
            row = sims[local_i].copy()
            row[i] = -2.0                  # exclude self
            top_idx = np.argpartition(row, -effective_k)[-effective_k:]
            for j in top_idx:
                j = int(j)
                score = float(row[j])
                if score < min_similarity:
                    continue
                pair = (i, j) if i < j else (j, i)
                if pair not in best or score > best[pair]:
                    best[pair] = score

    for (i, j), score in best.items():
        yield i, j, score


def iter_similar_pairs(vectors: np.ndarray, threshold: float, chunk_size: int = 512):
    """
    Yields (i, j, score) for every pair with cosine similarity >= threshold,
    i < j, without ever materializing the full N×N similarity matrix.

    Peak memory is O(chunk_size * n) instead of O(n * n) — e.g. for n=10,000
    and chunk_size=512, that's roughly 512*10,000*4 bytes (~20MB) per chunk
    instead of 10,000*10,000*4 bytes (~400MB) for the full matrix.
    """
    n = vectors.shape[0]
    if n == 0:
        return
    norm = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-8)

    for start in range(0, n, chunk_size):
        end = min(start + chunk_size, n)
        chunk = norm[start:end]              # (chunk_len, d)
        # Only compare each chunk row against everything from `start` onward,
        # so each unordered pair (i, j) is scored exactly once overall.
        sims = chunk @ norm[start:].T         # (chunk_len, n - start)
        for local_i in range(sims.shape[0]):
            i = start + local_i
            # j ranges over [i+1, n) within this chunk's comparison slice
            row = sims[local_i]
            for local_j in range(local_i + 1, row.shape[0]):
                j = start + local_j
                score = float(row[local_j])
                if score >= threshold:
                    yield i, j, score
