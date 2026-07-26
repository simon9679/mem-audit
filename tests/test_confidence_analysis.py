"""
Makes the accuracy claim reproducible without keys or a live run: reconstructs
the documented confidence-run outcome as data and checks that the scorer in
dev-scripts/analyze_confidence_test.py computes recall/precision from memory ids.

The reconstructed numbers are exactly runs 2 and 3 from the README:
  7 planted pairs, 10 findings, 7 landing on a planted pair (3 extra = false
  positives). Of the 7 matched, 2 (the UPDATE pairs) came back as CONTRADICTION
  instead of stale -> recall 7/7, precision 7/10, 5 correct type, 2 wrong type.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev-scripts"))

from analyze_confidence_test import score  # noqa: E402

# 7 planted pairs, ids stand in for Mem0 UUIDs.
PAIRS = {
    "dup1": {"type": "duplicate", "memory_ids": ["d1a", "d1b"]},
    "dup2": {"type": "duplicate", "memory_ids": ["d2a", "d2b"]},
    "dup3": {"type": "duplicate", "memory_ids": ["d3a", "d3b"]},
    "contra1": {"type": "contradiction", "memory_ids": ["c1a", "c1b"]},
    "contra2": {"type": "contradiction", "memory_ids": ["c2a", "c2b"]},
    "upd1": {"type": "stale", "memory_ids": ["u1a", "u1b"]},
    "upd2": {"type": "stale", "memory_ids": ["u2a", "u2b"]},
}

# 10 findings: 7 on planted pairs (upd1/upd2 mislabeled CONTRADICTION) + 3 FPs.
FINDINGS = [
    {"type": "duplicate", "memory_ids": ["d1a", "d1b"]},
    {"type": "duplicate", "memory_ids": ["d2a", "d2b"]},
    {"type": "duplicate", "memory_ids": ["d3a", "d3b"]},
    {"type": "contradiction", "memory_ids": ["c1a", "c1b"]},
    {"type": "contradiction", "memory_ids": ["c2a", "c2b"]},
    {"type": "contradiction", "memory_ids": ["u1b", "u1a"]},  # right pair, wrong type (order-insensitive)
    {"type": "contradiction", "memory_ids": ["u2a", "u2b"]},  # right pair, wrong type
    {"type": "duplicate", "memory_ids": ["u2b", "d3a"]},       # FP: data-analyst <-> engineering degree
    {"type": "duplicate", "memory_ids": ["d3b", "u2a"]},       # FP: again
    {"type": "duplicate", "memory_ids": ["d2a", "u2a"]},       # FP: commute <-> barista
]


def test_documented_run_scores_recall_7_of_7_precision_7_of_10():
    r = score(FINDINGS, PAIRS)
    assert r["recall"] == (7, 7)
    assert r["precision"] == (7, 10)
    assert r["correct_type"] == 5
    assert r["wrong_type"] == 2
    assert len(r["false_positives"]) == 3
    assert r["misses"] == []


def test_perfect_run_scores_clean():
    findings = [
        {"type": p["type"], "memory_ids": list(p["memory_ids"])} for p in PAIRS.values()
    ]
    r = score(findings, PAIRS)
    assert r["recall"] == (7, 7)
    assert r["precision"] == (7, 7)
    assert r["correct_type"] == 7
    assert r["wrong_type"] == 0
    assert r["false_positives"] == []
    assert r["misses"] == []


def test_match_is_order_insensitive_and_a_miss_is_reported():
    findings = [{"type": "duplicate", "memory_ids": ["d1b", "d1a"]}]  # only dup1, reversed
    r = score(findings, PAIRS)
    assert r["recall"] == (1, 7)
    assert r["precision"] == (1, 1)
    assert set(r["misses"]) == {"dup2", "dup3", "contra1", "contra2", "upd1", "upd2"}


if __name__ == "__main__":
    test_documented_run_scores_recall_7_of_7_precision_7_of_10()
    test_perfect_run_scores_clean()
    test_match_is_order_insensitive_and_a_miss_is_reported()
    print("Confidence-analysis scorer tests passed.")
