#!/usr/bin/env python3
"""Recompute canary paired-bootstrap CI from redacted verdict files.

Deterministic: fixed seed, no external state. Runs on the redacted files
that contain only index, verdict, finish_reason, and usage metadata.

Usage:
    python audit/canary/recompute_canary_ci.py [path/to/raw_redacted]

Default path: audit/canary/raw_redacted (relative to cwd).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

SEED = 20260811
SAMPLES = 10000


def main() -> int:
    redacted = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("audit/canary/raw_redacted")
    judges = redacted / "raw_judges"

    if not judges.is_dir():
        print(f"not found: {judges}", file=sys.stderr)
        return 1

    pairs: dict[int, dict[str, int]] = {}
    for f in sorted(judges.glob("*.json")):
        obj = json.loads(f.read_text(encoding="utf-8"))
        idx = obj["index"]
        verdict = obj["verdict"]
        correct = 1 if verdict in ("CORRECT", "ABSTAIN_CORRECT") else 0

        name = f.stem
        if "_MEMORY" in name and "_NO_MEMORY" not in name:
            arm = "memory"
        elif "_NO_MEMORY" in name:
            arm = "no_memory"
        else:
            print(f"cannot determine arm from {name}", file=sys.stderr)
            return 1

        pairs.setdefault(idx, {})[arm] = correct

    n = len(pairs)
    memory_correct = sum(p["memory"] for p in pairs.values())
    no_memory_correct = sum(p["no_memory"] for p in pairs.values())
    delta = memory_correct - no_memory_correct

    print(f"n={n}  memory_correct={memory_correct}  no_memory_correct={no_memory_correct}  delta={delta}")

    rng = np.random.default_rng(SEED)
    indices = list(sorted(pairs.keys()))
    mem = np.array([pairs[i]["memory"] for i in indices])
    nomem = np.array([pairs[i]["no_memory"] for i in indices])

    boot_deltas = np.empty(SAMPLES, dtype=int)
    for b in range(SAMPLES):
        pick = rng.integers(0, n, size=n)
        boot_deltas[b] = mem[pick].sum() - nomem[pick].sum()

    lo = int(np.percentile(boot_deltas, 2.5))
    hi = int(np.percentile(boot_deltas, 97.5))
    print(f"bootstrap ci95 delta_correct: [{lo}, {hi}]  (seed={SEED}, samples={SAMPLES})")
    print(f"published ci95 in CANARY_FINAL.json: [2, 13]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
