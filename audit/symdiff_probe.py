#!/usr/bin/env python3
r"""symdiff_probe — semantic symmetric-difference between two lists of strings.

Standalone. Measures how much two label sets diverge, matching labels not only
byte-for-byte but by meaning, so paraphrases ("joined a dating app" vs "joined
dating app") count as the same item above a cosine threshold.

Built to re-check the published 94.7% symmetric label difference between two
ingests of one 33-session dialogue (FULL_HISTORY.md §10 / evidence/_v12 §P4), and
to be pointed at another system later. The `exact` threshold reproduces the
byte-level number; the cosine thresholds show how much of the divergence is mere
re-wording of the same concepts.

Contract
--------
  python tools/symdiff_probe.py --a A.json --b B.json --json-out out.json

* --a / --b : JSON files, each a flat list of strings.
* Model     : all-MiniLM-L6-v2. No network beyond the one-time weight download.
              Zero LLM calls.
* Matching  : greedy one-to-one by descending cosine. Every string is in at most
              one pair.
* Thresholds: exact (byte equality), 0.60, 0.72, 0.82.
* Output    : per threshold |A|, |B|, |A\B|, |B\A|, symdiff % of |A ∪ B|, Jaccard
              — printed as a table AND written to --json-out.

Only external dependency: sentence-transformers (numpy ships with it). No imports
from any repository module.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List, Tuple

import numpy as np

MODEL_NAME = "all-MiniLM-L6-v2"
COSINE_THRESHOLDS = (0.60, 0.72, 0.82)


def load_labels(path: str) -> List[str]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        raise SystemExit(f"{path}: expected a JSON list of strings")
    return data


def greedy_match_exact(a: List[str], b: List[str]) -> int:
    """One-to-one matches by byte-identical equality. Returns matched-pair count."""
    from collections import Counter

    cb = Counter(b)
    m = 0
    for s in a:
        if cb.get(s, 0) > 0:
            cb[s] -= 1
            m += 1
    return m


def greedy_match_cosine(sim: np.ndarray, threshold: float) -> int:
    """Greedy one-to-one over the |A|x|B| cosine matrix, descending similarity.

    Every row (A) and column (B) is consumed at most once. Returns pair count."""
    n_a, n_b = sim.shape
    # candidate pairs above threshold, sorted by similarity descending
    idx = np.argwhere(sim >= threshold)
    if idx.size == 0:
        return 0
    order = np.argsort(-sim[idx[:, 0], idx[:, 1]], kind="stable")
    used_a = np.zeros(n_a, dtype=bool)
    used_b = np.zeros(n_b, dtype=bool)
    m = 0
    for k in order:
        i, j = int(idx[k, 0]), int(idx[k, 1])
        if used_a[i] or used_b[j]:
            continue
        used_a[i] = True
        used_b[j] = True
        m += 1
    return m


def stats(n_a: int, n_b: int, m: int) -> dict:
    union = n_a + n_b - m
    symdiff = n_a + n_b - 2 * m
    return {
        "matched": m,
        "A": n_a,
        "B": n_b,
        "A_minus_B": n_a - m,
        "B_minus_A": n_b - m,
        "union": union,
        "symdiff": symdiff,
        "symdiff_pct": round(100.0 * symdiff / union, 2) if union else 0.0,
        "jaccard": round(m / union, 4) if union else 0.0,
    }


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="Semantic symmetric-difference of two string lists.")
    ap.add_argument("--a", required=True, help="JSON file: list of strings (set A)")
    ap.add_argument("--b", required=True, help="JSON file: list of strings (set B)")
    ap.add_argument("--json-out", required=True, help="where to write the result JSON")
    args = ap.parse_args(argv)

    a = load_labels(args.a)
    b = load_labels(args.b)
    n_a, n_b = len(a), len(b)

    rows = {}

    # exact — byte equality, no embedding needed
    rows["exact"] = stats(n_a, n_b, greedy_match_exact(a, b))

    # cosine thresholds — one embedding pass, reused for all thresholds
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL_NAME)
    emb_a = model.encode(a, normalize_embeddings=True, convert_to_numpy=True)
    emb_b = model.encode(b, normalize_embeddings=True, convert_to_numpy=True)
    sim = emb_a @ emb_b.T  # cosine (unit-normalized)

    for t in COSINE_THRESHOLDS:
        rows[f"{t:.2f}"] = stats(n_a, n_b, greedy_match_cosine(sim, t))

    result = {
        "model": MODEL_NAME,
        "a_path": args.a,
        "b_path": args.b,
        "a_count": n_a,
        "b_count": n_b,
        "thresholds": rows,
    }
    with open(args.json_out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # table to stdout
    order = ["exact"] + [f"{t:.2f}" for t in COSINE_THRESHOLDS]
    header = f"{'threshold':<10} {'|A|':>4} {'|B|':>4} {'|A\\B|':>6} {'|B\\A|':>6} {'symdiff%':>9} {'Jaccard':>8}"
    print(header)
    print("-" * len(header))
    for key in order:
        r = rows[key]
        print(f"{key:<10} {r['A']:>4} {r['B']:>4} {r['A_minus_B']:>6} {r['B_minus_A']:>6} "
              f"{r['symdiff_pct']:>8.2f}% {r['jaccard']:>8.4f}")
    print(f"\nwrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
