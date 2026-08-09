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
    return [fact.get("text", "") for fact in payload["facts"]]


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2

    with tempfile.TemporaryDirectory(prefix="mem_audit_cmp_") as tmp:
        first = os.path.join(tmp, "first.json")
        second = os.path.join(tmp, "second.json")
        output = os.path.join(tmp, "result.json")
        with open(first, "w", encoding="utf-8") as fh:
            json.dump(_texts(sys.argv[1]), fh, ensure_ascii=False)
        with open(second, "w", encoding="utf-8") as fh:
            json.dump(_texts(sys.argv[2]), fh, ensure_ascii=False)
        return subprocess.run(
            [sys.executable, PROBE, "--a", first, "--b", second, "--json-out", output],
            check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
