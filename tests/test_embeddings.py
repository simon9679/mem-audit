"""
Offline tests for embedding batching (TZ task 1). No network, no tiktoken
required — a fake OpenAI-compatible client records every batch it's asked to
embed so we can assert on batch sizes and vector order.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from mem_audit.embeddings import (  # noqa: E402
    _iter_batches,
    _make_token_counter,
    openai_compatible_embedder,
)


class _FakeEmbeddings:
    def __init__(self, parent):
        self._parent = parent

    def create(self, model, input):
        # Record the exact batch handed to this call for later assertions.
        self._parent.calls.append(list(input))
        # Embed each text as a vector that encodes its own marker index, so a
        # reordering anywhere in the pipeline is detectable in the output.
        data = []
        for text in input:
            idx = int(text.split("-")[1])
            data.append(_Item([float(idx), 0.0, 0.0]))
        return _Resp(data)


class _Item:
    def __init__(self, embedding):
        self.embedding = embedding


class _Resp:
    def __init__(self, data):
        self.data = data


class FakeClient:
    def __init__(self):
        self.calls = []
        self.embeddings = _FakeEmbeddings(self)


def test_large_input_is_split_by_item_ceiling_order_preserved():
    n = 5000
    texts = [f"marker-{i}" for i in range(n)]
    client = FakeClient()
    embed = openai_compatible_embedder(
        model="text-embedding-3-small", client=client, max_batch_items=128, max_batch_tokens=250_000
    )

    vectors = embed(texts)

    # Client was called more than once (single-call would blow past limits).
    assert len(client.calls) > 1
    # No batch exceeds the item ceiling.
    for batch in client.calls:
        assert len(batch) <= 128
    # Every text embedded exactly once, no drops/dupes.
    assert sum(len(b) for b in client.calls) == n
    # Final matrix shape and 1:1 order (row i encodes marker i).
    assert vectors.shape == (n, 3)
    for i in range(n):
        assert vectors[i][0] == float(i), f"row {i} out of order"


def test_empty_input_returns_zero_matrix_without_calling_client():
    client = FakeClient()
    embed = openai_compatible_embedder(model="text-embedding-3-small", client=client)
    vectors = embed([])
    assert vectors.shape == (0, 1536)
    assert client.calls == []


def test_single_text_one_call():
    client = FakeClient()
    embed = openai_compatible_embedder(model="text-embedding-3-small", client=client)
    vectors = embed(["marker-0"])
    assert len(client.calls) == 1
    assert vectors.shape == (1, 3)


def test_token_ceiling_closes_batch():
    # Test the batching threshold logic directly with a deterministic token
    # counter (1 token per char), so the assertion doesn't depend on whether
    # tiktoken is installed. With a 3-token ceiling and 6 one-char texts,
    # every batch must stay at or under 3 tokens.
    texts = ["a", "b", "c", "d", "e", "f"]
    batches = list(
        _iter_batches(texts, count_tokens=lambda t: len(t), max_batch_items=1000, max_batch_tokens=3)
    )
    assert len(batches) > 1
    for batch in batches:
        assert sum(len(t) for t in batch) <= 3
    # Order and completeness preserved across batches.
    assert [t for batch in batches for t in batch] == texts


def test_oversized_single_text_still_emitted_alone():
    # A text bigger than the whole token budget can't be split — it must still
    # go out (in a batch by itself) rather than being dropped.
    texts = ["x" * 100, "y"]
    batches = list(
        _iter_batches(texts, count_tokens=lambda t: len(t), max_batch_items=1000, max_batch_tokens=10)
    )
    assert [t for batch in batches for t in batch] == texts
    assert ["x" * 100] in batches


def test_token_counter_falls_back_gracefully():
    # Whether or not tiktoken is installed, the counter is callable and returns
    # a positive integer for non-empty text.
    count = _make_token_counter("text-embedding-3-small")
    assert count("hello world") >= 1
    count_prefixed = _make_token_counter("openai/text-embedding-3-small")
    assert count_prefixed("hello world") >= 1


if __name__ == "__main__":
    test_large_input_is_split_by_item_ceiling_order_preserved()
    test_empty_input_returns_zero_matrix_without_calling_client()
    test_single_text_one_call()
    test_token_ceiling_closes_batch()
    test_oversized_single_text_still_emitted_alone()
    test_token_counter_falls_back_gracefully()
    print("Embedding batching tests passed.")
