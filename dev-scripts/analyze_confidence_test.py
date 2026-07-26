"""
Scores a confidence run mechanically: matches findings to the planted pairs by
Mem0 id (from confidence_ground_truth.json, written by confidence_test_seed.py),
not by eyeballing paraphrased summaries. Prints recall, precision, how many
finds had the right TYPE vs the right pair but wrong type, plus the false
positives and misses — and the run metadata, so the result is self-describing.

Run: python dev-scripts/analyze_confidence_test.py
     [--report confidence_report.json] [--ground-truth confidence_ground_truth.json]

Importable: `score(findings, pairs)` is pure (stdlib only), so the accuracy
claim is unit-testable without keys or a live run.
"""
from __future__ import annotations

import argparse
import json


def score(findings: list[dict], pairs: dict[str, dict]) -> dict:
    """
    Match findings to planted pairs by id-set and tally the outcome.

    findings: list of {"type": str, "memory_ids": [id, id]}.
    pairs:    {pair_name: {"type": str, "memory_ids": [id, id]}}.

    A finding matches a pair when their memory-id sets are equal. Recall counts
    distinct planted pairs found; precision counts findings that hit a planted
    pair over all findings. "correct type" is a matched pair whose finding type
    equals the planted type; "wrong type" is the right pair with the wrong type.
    """
    pair_by_ids = {frozenset(p["memory_ids"]): name for name, p in pairs.items()}

    matched: dict[str, str] = {}  # pair name -> the finding type that hit it
    false_positives: list[dict] = []
    for f in findings:
        key = frozenset(f.get("memory_ids", []))
        name = pair_by_ids.get(key)
        if name is None:
            false_positives.append(f)
        elif name not in matched:
            matched[name] = f.get("type")

    correct_type = sum(1 for name, ftype in matched.items() if ftype == pairs[name]["type"])
    tp = len(findings) - len(false_positives)  # findings landing on a planted pair
    return {
        "planted_pairs": len(pairs),
        "found_pairs": len(matched),
        "recall": (len(matched), len(pairs)),
        "precision": (tp, len(findings)),
        "correct_type": correct_type,
        "wrong_type": len(matched) - correct_type,
        "false_positives": false_positives,
        "misses": [name for name in pairs if name not in matched],
    }


def _split_report(report):
    """Return (metadata_or_None, findings) for both report shapes (object/list)."""
    if isinstance(report, dict):
        return report.get("metadata"), report.get("findings", [])
    return None, report


def _fmt(n_d):
    n, d = n_d
    return f"{n}/{d}" + (f" ({n / d:.0%})" if d else "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="confidence_report.json")
    ap.add_argument("--ground-truth", default="confidence_ground_truth.json")
    args = ap.parse_args()

    with open(args.report, encoding="utf-8") as fh:
        metadata, findings = _split_report(json.load(fh))
    with open(args.ground_truth, encoding="utf-8") as fh:
        pairs = json.load(fh)["pairs"]

    result = score(findings, pairs)

    print("=" * 66)
    print("CONFIDENCE RUN - mechanical score (matched by memory id)")
    print("=" * 66)
    if metadata:
        emb, jud = metadata.get("embedder", {}), metadata.get("judge", {})
        print(f"run_at:   {metadata.get('run_at')}   version: {metadata.get('version')}")
        print(f"embedder: {emb.get('provider')} / {emb.get('model')}")
        print(f"judge:    {jud.get('provider')} / {jud.get('model')}")
        print(f"scanned:  {metadata.get('memories_scanned')}   "
              f"candidate pairs: {metadata.get('candidate_pairs')}   "
              f"verdicts: {metadata.get('judge_verdicts')}")
    else:
        print("(report has no metadata — an older bare-list report)")
    print("-" * 66)
    print(f"recall   : {_fmt(result['recall'])}   (planted pairs found)")
    print(f"precision: {_fmt(result['precision'])}   (findings that hit a planted pair)")
    print(f"of found pairs - correct type: {result['correct_type']}, "
          f"wrong type: {result['wrong_type']}")
    if result["misses"]:
        print(f"MISSED pairs   : {', '.join(result['misses'])}")
    else:
        print("MISSED pairs   : none")
    if result["false_positives"]:
        print(f"FALSE positives: {len(result['false_positives'])}")
        for f in result["false_positives"]:
            print(f"  - [{f.get('type')}] {f.get('summary', f.get('memory_ids'))}")
    else:
        print("FALSE positives: none")


if __name__ == "__main__":
    main()
