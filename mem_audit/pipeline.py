from __future__ import annotations

from typing import Callable

from mem_audit.connectors.mem0_connector import Mem0Connector
from mem_audit.detectors.base import Finding
from mem_audit.detectors.contradictions import LLMCallFn, find_contradictions
from mem_audit.detectors.duplicates import DEFAULT_MIN_SIMILARITY, DEFAULT_TOP_K, find_duplicate_candidates
from mem_audit.embeddings import EmbedFn


def run_audit(
    mem0_client,
    user_id: str,
    embed_fn: EmbedFn,
    llm_call: LLMCallFn,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    similarity_threshold: float | None = None,
    page_size: int = 500,
    on_progress: Callable[[int, int], None] | None = None,
    on_stage: Callable[[str], None] | None = None,
) -> tuple[list[Finding], int]:
    """
    Full pipeline: fetch -> cheap embedding-similarity pass -> LLM judge on
    the candidates the cheap pass surfaced.

    Cheap-pass strategy is top-k nearest neighbors by default (top_k,
    min_similarity) rather than a fixed cosine cutoff — see
    detectors/duplicates.py and embeddings.top_k_neighbor_pairs for why a
    single absolute threshold is the wrong tool for OpenAI-family
    embeddings. Pass similarity_threshold=<float> explicitly to opt into
    the old fixed-threshold behavior instead.

    The judge is the *only* source of Findings for candidate pairs — the
    cheap pass just narrows down which pairs are worth judging. This
    matters: a pair the judge calls UNRELATED produces no Finding, full
    stop. (An earlier version let the cheap pass's own Finding survive
    regardless of the judge's verdict, which meant embedding-similarity
    false positives could show up in the report as "duplicates" even after
    the judge said they weren't related. Fixed by removing the cheap pass's
    ability to emit Findings at all — see detectors/duplicates.py.)

    Returns (findings, total_memories_scanned).
    """
    connector = Mem0Connector(mem0_client)
    records = connector.fetch_all(user_id=user_id, page_size=page_size)

    if len(records) < 2:
        return [], len(records)

    if on_stage:
        on_stage(f"Computing embeddings for {len(records)} memories...")

    candidate_pairs = find_duplicate_candidates(
        records,
        embed_fn,
        top_k=top_k,
        min_similarity=min_similarity,
        threshold=similarity_threshold,
    )

    if on_stage:
        on_stage(f"Found {len(candidate_pairs)} candidate pair(s) — judging...")

    findings = find_contradictions(candidate_pairs, llm_call, on_progress=on_progress)
    return findings, len(records)
