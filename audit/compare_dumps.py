#!/usr/bin/env python3
"""Compare two audit fact dumps with the published symmetric-difference metric.

    python audit/compare_dumps.py <dump_A.json> <dump_B.json>

The audit dumps are objects with a ``facts`` array, whereas ``symdiff_probe.py``
expects a JSON list of strings. This adapter extracts the fact text and passes it
to the unchanged metric. It needs ``sentence-transformers`` for the local
all-MiniLM-L6-v2 model; no LLM calls are made.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile


HERE = os.path.dirname(os.path.abspath(__file__))
PROBE = os.path.join(HERE, "symdiff_probe.py")


def _texts(path: str) -> list[str]:
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    facts = payload.get("facts") if isinstance(payload, dict) else None
    if not isinstance(facts, list):
        raise ValueError(f"{path}: expected an object with a 'facts' array")

    texts: list[str] = []
    for index, fact in enumerate(facts):
        if not isinstance(fact, dict):
            raise ValueError(f"{path}: facts[{index}] must be an object")
        for field in ("text", "memory"):
            value = fact.get(field)
            if isinstance(value, str) and value.strip():
                texts.append(value)
                break
        else:
            raise ValueError(
                f"{path}: facts[{index}] needs a non-empty string 'text' or 'memory' field"
            )
    return texts


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2

    try:
        first_texts = _texts(sys.argv[1])
        second_texts = _texts(sys.argv[2])
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"compare_dumps: {error}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="mem_audit_cmp_") as tmp:
        first = os.path.join(tmp, "first.json")
        second = os.path.join(tmp, "second.json")
        output = os.path.join(tmp, "result.json")
        with open(first, "w", encoding="utf-8") as fh:
            json.dump(first_texts, fh, ensure_ascii=False)
        with open(second, "w", encoding="utf-8") as fh:
            json.dump(second_texts, fh, ensure_ascii=False)
        return subprocess.run(
            [sys.executable, PROBE, "--a", first, "--b", second, "--json-out", output],
            check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
