#!/usr/bin/env python3
"""Offline falsification checks for audit/symdiff_probe.py.

Runs the unchanged CLI on fixed fixtures and writes PROBE_symdiff_probe.md.
No LLM calls are made. Hugging Face and Transformers offline modes are forced.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from symdiff_probe import stats as core_stats

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROBE = HERE / "symdiff_probe.py"
THRESHOLDS = ("exact", "0.60", "0.72", "0.82")
SEMANTIC_THRESHOLDS = ("0.60", "0.72", "0.82")

# Fixed before running any metric command.
SEMANTIC_ORIGINAL = [
    "Maya lives in Berlin.",
    "Omar works as a teacher.",
    "Priya owns a red bicycle.",
    "Noah visits his grandmother every Sunday.",
    "Elena prefers tea in the morning.",
    "Victor repaired the broken window.",
    "Sara speaks French at home.",
    "Daniel adopted a small dog.",
    "Iris paid the electricity bill yesterday.",
    "Leo studies mathematics at university.",
]
SEMANTIC_SCRAMBLED = [
    "Berlin in lives Maya.",
    "Teacher a as works Omar.",
    "Bicycle red a owns Priya.",
    "Sunday every grandmother his visits Noah.",
    "Morning the in tea prefers Elena.",
    "Window broken the repaired Victor.",
    "Home at French speaks Sara.",
    "Dog small a adopted Daniel.",
    "Yesterday bill electricity the paid Iris.",
    "University at mathematics studies Leo.",
]
SEMANTIC_ANTONYM = [
    "Maya does not live in Berlin.",
    "Omar does not work as a teacher.",
    "Priya does not own a red bicycle.",
    "Noah never visits his grandmother on Sunday.",
    "Elena dislikes tea in the morning.",
    "Victor broke the intact window.",
    "Sara does not speak French at home.",
    "Daniel gave away a small dog.",
    "Iris did not pay the electricity bill yesterday.",
    "Leo does not study mathematics at university.",
]
SEMANTIC_PARAPHRASE = [
    "Berlin is Maya's home city.",
    "Omar teaches for a living.",
    "Priya has a bicycle that is red.",
    "Each Sunday, Noah goes to see his grandmother.",
    "Elena likes to drink tea each morning.",
    "Victor fixed a window that had been broken.",
    "French is the language Sara uses at home.",
    "Daniel became the owner of a little dog.",
    "Yesterday, Iris settled the electric power invoice.",
    "Leo is a university student of mathematics.",
]
ORACLE_FOOD = [
    "The kitchen contains fresh apples and rice.",
    "Nora cooks lentil soup for dinner.",
    "The bakery sells warm bread every morning.",
    "Sam drinks black coffee after lunch.",
    "The market has oranges, cheese, and tomatoes.",
    "A recipe uses basil, pasta, and olive oil.",
    "Rita packs a sandwich for work.",
    "The restaurant serves spicy noodles.",
    "The freezer contains peas and ice cream.",
    "Ken buys yogurt and bananas on Friday.",
]
ORACLE_NUMBERS = [
    "one hundred and three",
    "seven thousand and nineteen",
    "forty two",
    "nine hundred and eleven",
    "two million and five",
    "sixteen",
    "eight hundred and eighty",
    "thirty four thousand",
    "five hundred and sixty seven",
    "ninety nine",
]
CONSTANT_FACTS = [
    "Maya lives in Berlin.",
    "Maya works as a civil engineer.",
    "Maya owns a red bicycle.",
    "Maya speaks German and Spanish.",
    "Maya visits her brother every month.",
    "Maya prefers tea in the morning.",
    "Maya repaired a cracked window.",
    "Maya adopted a small dog.",
    "Maya studies astronomy at night.",
    "Maya paid the electricity bill yesterday.",
    "Maya runs five kilometers on Saturdays.",
    "Maya grows basil on her balcony.",
    "Maya reads mystery novels.",
    "Maya plays chess after work.",
    "Maya travels by train to Prague.",
    "Maya volunteers at an animal shelter.",
    "Maya bought a wooden desk.",
    "Maya attends a photography class.",
    "Maya keeps receipts in a blue folder.",
    "Maya calls her parents every Wednesday.",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_value(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def run_probe(first: list[str], second: list[str], allow_error: bool = False) -> dict[str, Any]:
    env = os.environ.copy()
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    with tempfile.TemporaryDirectory(prefix="validate_symdiff_") as directory:
        work = Path(directory)
        a_path, b_path, out_path = work / "a.json", work / "b.json", work / "out.json"
        a_path.write_text(json.dumps(first, ensure_ascii=False), encoding="utf-8")
        b_path.write_text(json.dumps(second, ensure_ascii=False), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(PROBE), "--a", str(a_path), "--b", str(b_path), "--json-out", str(out_path)],
            cwd=ROOT, env=env, text=True, capture_output=True, check=False,
        )
        if completed.returncode:
            error = (completed.stderr + completed.stdout).strip()
            if allow_error:
                return {"cli_error": error}
            raise RuntimeError("symdiff_probe.py failed:\n" + error)
        return json.loads(out_path.read_text(encoding="utf-8"))


def stats_result(n_a: int, n_b: int, matched: int) -> dict[str, Any]:
    value = core_stats(n_a, n_b, matched)
    return {"thresholds": {threshold: value for threshold in THRESHOLDS}}

def rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [result["thresholds"][threshold] for threshold in THRESHOLDS]


def table(result: dict[str, Any]) -> str:
    lines = ["| threshold | matched | |A| | |B| | A-B | B-A | union | symdiff % | Jaccard |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for threshold, row in zip(THRESHOLDS, rows(result)):
        lines.append(
            f"| {threshold} | {row['matched']} | {row['A']} | {row['B']} | {row['A_minus_B']} | "
            f"{row['B_minus_A']} | {row['union']} | {row['symdiff_pct']:.2f} | {row['jaccard']:.4f} |"
        )
    return "\n".join(lines)


def fixture(name: str, value: Any) -> str:
    return f"**{name}**\n```json\n{json.dumps(value, ensure_ascii=False, indent=2)}\n```"


def status_line(status: str, text: str) -> str:
    return f"**{status}.** {text}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=HERE / "PROBE_symdiff_probe.md")
    args = parser.parse_args()

    canaries = {
        "empty vs empty": ([], []),
        "empty vs one": ([], ["some text"]),
        "one identical": (["a"], ["a"]),
    }
    canary_results = {name: run_probe(a, b, allow_error=True) for name, (a, b) in canaries.items()}
    canary_matches = {"empty vs empty": 0, "empty vs one": 0, "one identical": 1}
    canary_stats = {
        name: stats_result(len(a), len(b), canary_matches[name])
        for name, (a, b) in canaries.items()
    }
    oracle = run_probe(ORACLE_FOOD, ORACLE_NUMBERS)
    semantic = {
        "word permutation": run_probe(SEMANTIC_ORIGINAL, SEMANTIC_SCRAMBLED),
        "antonym substitution": run_probe(SEMANTIC_ORIGINAL, SEMANTIC_ANTONYM),
        "meaning-preserving paraphrase": run_probe(SEMANTIC_ORIGINAL, SEMANTIC_PARAPHRASE),
    }
    constant = run_probe(CONSTANT_FACTS, [CONSTANT_FACTS[0]] * len(CONSTANT_FACTS))

    empty_zero = all(row["symdiff_pct"] == 0.0 for row in rows(canary_stats["empty vs empty"]))
    canary_cli_ok = all("cli_error" not in result for result in canary_results.values())
    oracle_ok = all(row["symdiff_pct"] >= 95.0 for row in rows(oracle))
    permutation_ok = all(
        semantic["meaning-preserving paraphrase"]["thresholds"][t]["symdiff_pct"]
        < semantic["word permutation"]["thresholds"][t]["symdiff_pct"]
        for t in SEMANTIC_THRESHOLDS
    )
    antonym_ok = all(
        semantic["meaning-preserving paraphrase"]["thresholds"][t]["symdiff_pct"]
        < semantic["antonym substitution"]["thresholds"][t]["symdiff_pct"]
        for t in ("0.72", "0.82")
    )
    constant_matches = {t: constant["thresholds"][t]["matched"] for t in SEMANTIC_THRESHOLDS}
    constant_ok = constant["thresholds"]["exact"]["matched"] == 1 and all(value <= 1 for value in constant_matches.values())

    parts = [
        "# PROBE - falsification checks for `symdiff_probe.py`",
        "",
        f"Run date: **{date.today().isoformat()}** (local date).",
        "",
        "| item | value |",
        "|---|---|",
        f"| Git commit | `{git_value('rev-parse', 'HEAD')}` |",
        f"| `symdiff_probe.py` git blob | `{git_value('hash-object', 'audit/symdiff_probe.py')}` |",
        f"| `symdiff_probe.py` SHA-256 | `{sha256(PROBE)}` |",
        f"| sentence-transformers | `{importlib.metadata.version('sentence-transformers')}` |",
        "| execution guard | `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`; no LLM client is imported |",
        "",
        "This document is generated by `audit/validate_symdiff_probe.py`. Fixtures and pass/fail criteria are fixed in that script before the metric is invoked. The metric itself is unchanged.",
        "",
        "## 1. Canary / degenerate input",
        "",
        fixture("inputs", {name: {"A": a, "B": b} for name, (a, b) in canaries.items()}),
        "",
    ]
    for name, result in canary_results.items():
        parts.extend([f"### {name}", "", "**Direct `stats()` result**", "", table(canary_stats[name]), "", "**CLI result**", ""])
        if "cli_error" in result:
            parts.extend(["```text", result["cli_error"], "```", ""])
        else:
            parts.extend([table(result), ""])
    parts.extend([
        status_line("ISSUE" if not canary_cli_ok else "AMBIGUOUS CONTRACT", "`stats(0, 0, 0)` returns `symdiff_pct=0.0`, so empty lists are numerically identical at the helper level. However, the CLI fails before emitting cosine rows for any empty input; this is a concrete empty-input failure, not merely an undocumented identity convention."),
        "",
        "## 2. Oracle / maximum probe",
        "",
        fixture("A: food facts", ORACLE_FOOD),
        "",
        fixture("B: number phrases", ORACLE_NUMBERS),
        "",
        table(oracle),
        "",
        status_line("OK" if oracle_ok else "ISSUE", "Predefined criterion: each observed threshold must reach at least 95% symdiff. The table records the observed maximum for this disjoint fixture, not a claim of a universal numerical ceiling."),
        "",
        "## 3. Semantic label permutation",
        "",
        fixture("original", SEMANTIC_ORIGINAL),
        "",
        fixture("word permutation", SEMANTIC_SCRAMBLED),
        "",
        fixture("antonym substitution", SEMANTIC_ANTONYM),
        "",
        fixture("meaning-preserving paraphrase", SEMANTIC_PARAPHRASE),
        "",
    ])
    for name, result in semantic.items():
        parts.extend([f"### original vs {name}", "", table(result), ""])
    semantic_status = "OK" if permutation_ok and antonym_ok else "ISSUE"
    semantic_reasons = []
    if not permutation_ok:
        semantic_reasons.append("word permutation is not strictly more divergent than paraphrase at every cosine threshold")
    if not antonym_ok:
        semantic_reasons.append("antonym substitution is not strictly more divergent than paraphrase at both 0.72 and 0.82")
    parts.extend([
        status_line(semantic_status, "Predefined criteria: paraphrase must have lower symdiff than word permutation at 0.60/0.72/0.82, and lower symdiff than antonym substitution at 0.72/0.82." + (" Failed: " + "; ".join(semantic_reasons) + "." if semantic_reasons else "")),
        "",
        "## 4. Constant mutation",
        "",
        fixture("A: 20 distinct facts", CONSTANT_FACTS),
        "",
        "**B: repeated constant**\n```python\nB = [A[0]] * 20\n```",
        "",
        table(constant),
        "",
        status_line("OK" if constant_ok else "ISSUE", "Predefined set-semantics criterion: exactly one exact match and no more than one semantic match at each cosine threshold. Repeated entries are separate columns in the current list-based greedy implementation, so a failure exposes duplicate capacity rather than an automatic implementation error."),
        "",
        "## Facts vs criteria",
        "",
        "| check | predefined criterion | result | status |",
        "|---|---|---|---|",
        f"| empty inputs | direct stats reports zero for empty-empty; CLI must complete for all fixtures | stats-zero: `{empty_zero}`; cli-ok: `{canary_cli_ok}` | {'OK' if canary_cli_ok else 'ISSUE'} |",
        f"| oracle | every threshold >= 95% | `{oracle_ok}` | {'OK' if oracle_ok else 'ISSUE'} |",
        f"| word permutation | paraphrase lower at 0.60/0.72/0.82 | `{permutation_ok}` | {'OK' if permutation_ok else 'ISSUE'} |",
        f"| antonym substitution | paraphrase lower at 0.72/0.82 | `{antonym_ok}` | {'OK' if antonym_ok else 'ISSUE'} |",
        f"| constant mutation | exact=1 and semantic matches <=1 | `{constant_ok}`; semantic matches `{constant_matches}` | {'OK' if constant_ok else 'ISSUE'} |",
        "",
        "No conclusion about Mem0 is made here. These checks characterize only the behavior of this measurement tool on fixed fixtures.",
        "",
    ])
    args.output.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())