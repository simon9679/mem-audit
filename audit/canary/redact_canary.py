#!/usr/bin/env python3
"""Redact p8-derived text fields from canary_05 raw data.

Keeps only the fields needed for CI recomputation:
  index, arm, verdict, finish_reason,
  raw_response.model, raw_response.usage, raw_response.time_info

Fails with exit code 1 if any field outside the known set is encountered.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

KEEP_TOP = {"index", "arm", "verdict", "finish_reason"}
REMOVE_TOP = {"question", "gold_answer", "candidate_answer", "answer", "context", "raw_text"}
KNOWN_TOP = KEEP_TOP | REMOVE_TOP | {"raw_response"}

KEEP_RAW_RESPONSE = {"model", "usage", "time_info"}
KNOWN_RAW_RESPONSE = KEEP_RAW_RESPONSE | {
    "id", "created", "object", "system_fingerprint",
    "choices", "service_tier",
}


def redact(obj: dict, path: str) -> dict:
    unknown_top = set(obj.keys()) - KNOWN_TOP
    if unknown_top:
        print(f"FATAL: {path}: unknown top-level fields: {unknown_top}", file=sys.stderr)
        sys.exit(1)

    out: dict = {}
    for key in KEEP_TOP:
        if key in obj:
            out[key] = obj[key]

    if "raw_response" in obj:
        rr = obj["raw_response"]
        unknown_rr = set(rr.keys()) - KNOWN_RAW_RESPONSE
        if unknown_rr:
            print(f"FATAL: {path}: unknown raw_response fields: {unknown_rr}", file=sys.stderr)
            sys.exit(1)
        out["raw_response"] = {k: rr[k] for k in KEEP_RAW_RESPONSE if k in rr}

    return out


def process_dir(src: Path, dst: Path) -> int:
    count = 0
    for f in sorted(src.rglob("*.json")):
        rel = f.relative_to(src)
        obj = json.loads(f.read_text(encoding="utf-8"))
        redacted = redact(obj, str(rel))
        out_path = dst / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(redacted, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("src", type=Path, help="canary_05 source directory")
    parser.add_argument("dst", type=Path, help="output directory for redacted files")
    args = parser.parse_args()

    if not args.src.is_dir():
        print(f"source not found: {args.src}", file=sys.stderr)
        return 1

    if args.dst.exists():
        print(f"destination already exists: {args.dst}", file=sys.stderr)
        return 1

    judges_src = args.src / "raw_judges"
    answers_src = args.src / "raw_answers"

    total = 0
    if judges_src.is_dir():
        total += process_dir(judges_src, args.dst / "raw_judges")
    if answers_src.is_dir():
        total += process_dir(answers_src, args.dst / "raw_answers")

    print(f"redacted {total} files -> {args.dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
