"""
Offline demo — no API keys, no network required.

Reproduces the exact failure mode from mem0ai/mem0#4896: Mem0's ADD-only
extraction stores "my name is LGY" and later "my name is LGS" as two
separate ADD events instead of resolving the contradiction. get_all()
then returns both, and mem-audit is what catches it.

Run: python examples/demo_offline.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running directly (`python examples/demo_offline.py`) before
# the package is pip-installed.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from mem_audit.pipeline import run_audit
from mem_audit.report import print_report


class FakeMem0Client:
    """Stand-in for `mem0.Memory` — same get_all() contract, no real backend."""

    def __init__(self, items: list[dict]):
        self._items = items

    def get_all(self, filters: dict, top_k: int = 500):
        user_id = filters["user_id"]
        return {"results": [i for i in self._items if i["user_id"] == user_id][:top_k]}

    def history(self, memory_id: str):
        return []


# Synthetic memory store, modeled directly on the mem0ai/mem0#4896 repro case
# plus two extra pairs to exercise DUPLICATE and UPDATE classification.
FAKE_MEMORIES = [
    {"id": "m1", "user_id": "demo", "memory": "My name is LGY", "created_at": "2026-01-01T00:00:00"},
    {"id": "m2", "user_id": "demo", "memory": "My name is LGS", "created_at": "2026-01-05T00:00:00"},
    {"id": "m3", "user_id": "demo", "memory": "I live in Berlin", "created_at": "2026-02-01T00:00:00"},
    {"id": "m4", "user_id": "demo", "memory": "I live in Madrid", "created_at": "2026-03-01T00:00:00"},
    {"id": "m5", "user_id": "demo", "memory": "I enjoy playing chess on weekends", "created_at": "2026-01-10T00:00:00"},
    {"id": "m6", "user_id": "demo", "memory": "I like playing chess on the weekend", "created_at": "2026-01-11T00:00:00"},
    {"id": "m7", "user_id": "demo", "memory": "I work as a nurse", "created_at": "2026-01-15T00:00:00"},
    # This pair exists specifically to prove the UNRELATED-leak fix: their
    # embeddings are hand-placed close together below (a plausible false
    # positive from the cheap pass), but the judge should call them
    # UNRELATED — and the report must then show *nothing* for this pair.
    {"id": "m8", "user_id": "demo", "memory": "I adopted a cat named Luna", "created_at": "2026-04-01T00:00:00"},
    {"id": "m9", "user_id": "demo", "memory": "I watched a documentary about lunar missions", "created_at": "2026-04-02T00:00:00"},
]

# Deterministic fake embeddings: pairs we want flagged as "close" get
# hand-placed nearby vectors. This replaces a real embedding model so the
# demo runs with zero network calls.
_FAKE_VECTORS = {
    "My name is LGY": [1.0, 0.0, 0.0, 0.0, 0.0],
    "My name is LGS": [0.98, 0.05, 0.0, 0.0, 0.0],          # close to m1 -> contradiction candidate
    "I live in Berlin": [0.0, 1.0, 0.0, 0.0, 0.0],
    "I live in Madrid": [0.02, 0.97, 0.0, 0.0, 0.0],         # close to m3 -> contradiction candidate
    "I enjoy playing chess on weekends": [0.0, 0.0, 1.0, 0.0, 0.0],
    "I like playing chess on the weekend": [0.01, 0.0, 0.98, 0.02, 0.0],  # close to m5 -> duplicate
    "I work as a nurse": [0.0, 0.0, 0.0, 1.0, 0.0],           # not close to anything
    "I adopted a cat named Luna": [0.0, 0.0, 0.0, 0.0, 1.0],
    "I watched a documentary about lunar missions": [0.0, 0.0, 0.0, 0.02, 0.97],  # close to m8, but unrelated
}


def fake_embed_fn(texts):
    return np.array([_FAKE_VECTORS[t] for t in texts], dtype=np.float32)


def fake_llm_judge(prompt: str) -> str:
    """Canned judge: pattern-matches on which pair is being asked about."""
    if "LGY" in prompt and "LGS" in prompt:
        return '{"label": "CONTRADICTION", "rationale": "Two different names cannot both be the user\'s current name."}'
    if "Berlin" in prompt and "Madrid" in prompt:
        return '{"label": "UPDATE", "rationale": "User likely moved from Berlin to Madrid; older fact should be retired."}'
    if "chess" in prompt:
        return '{"label": "DUPLICATE", "rationale": "Same fact, reworded."}'
    if "Luna" in prompt and "lunar" in prompt:
        return '{"label": "UNRELATED", "rationale": "A pet\'s name and a documentary topic are not the same fact — embedding similarity was a false positive."}'
    return '{"label": "UNRELATED", "rationale": "Not the same fact."}'


if __name__ == "__main__":
    client = FakeMem0Client(FAKE_MEMORIES)
    findings, total = run_audit(
        mem0_client=client,
        user_id="demo",
        embed_fn=fake_embed_fn,
        llm_call=fake_llm_judge,
        min_similarity=0.30,
    )
    print_report(findings, total_memories=total, user_id="demo")
