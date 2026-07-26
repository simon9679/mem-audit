"""
Offline tests for report rendering and JSON export. No network, no keys — we
render into an in-memory buffer and assert on the text, and round-trip
export_json through a temp file.
"""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rich.console import Console  # noqa: E402

from mem_audit import report as report_module  # noqa: E402
from mem_audit.detectors.base import Finding, FindingType, Severity, finding_to_dict  # noqa: E402
from mem_audit.report import export_json, print_report  # noqa: E402


def _findings_all_severities():
    # Deliberately NOT in severity order on input, so the sort has to do work.
    return [
        Finding(
            type=FindingType.DUPLICATE,
            severity=Severity.LOW,
            memory_ids=["m5", "m6"],
            summary="LOWSUMMARY duplicate fact",
            suggested_action="merge",
        ),
        Finding(
            type=FindingType.CONTRADICTION,
            severity=Severity.HIGH,
            memory_ids=["m1", "m2"],
            summary="HIGHSUMMARY contradicting cities",
            suggested_action="pick one",
        ),
        Finding(
            type=FindingType.STALE,
            severity=Severity.MEDIUM,
            memory_ids=["m3", "m4"],
            summary="MEDSUMMARY likely superseded",
            suggested_action="retire older",
        ),
    ]


def _render(findings):
    """Render print_report into a plain-text buffer and return the string."""
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=200)
    # print_report builds its own Console(); swap it for our capture one.
    original = report_module.Console
    report_module.Console = lambda *a, **k: console
    try:
        print_report(findings, total_memories=9, user_id="demo")
    finally:
        report_module.Console = original
    return buf.getvalue()


def test_report_sorts_highest_severity_first():
    out = _render(_findings_all_severities())
    hi = out.index("HIGHSUMMARY")
    med = out.index("MEDSUMMARY")
    lo = out.index("LOWSUMMARY")
    assert hi < med < lo, f"expected HIGH < MEDIUM < LOW, got {hi}, {med}, {lo}"


def test_empty_findings_prints_clean_message_without_crashing():
    out = _render([])
    assert "No duplicates, contradictions, or stale facts found." in out


def test_export_json_serializes_enums_to_strings_and_round_trips():
    findings = _findings_all_severities()
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        export_json(findings, path)
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)  # raises if not valid JSON
    finally:
        os.unlink(path)

    assert isinstance(data, list)
    assert len(data) == len(findings)
    severities = {row["severity"] for row in data}
    types = {row["type"] for row in data}
    # Plain strings, not "Severity.HIGH" enum reprs.
    assert severities == {"high", "medium", "low"}
    assert types == {"contradiction", "stale", "duplicate"}
    for row in data:
        assert isinstance(row["severity"], str)
        assert isinstance(row["type"], str)
        assert isinstance(row["memory_ids"], list)


def test_finding_to_dict_matches_export_shape():
    (finding,) = [
        Finding(
            type=FindingType.CONTRADICTION,
            severity=Severity.HIGH,
            memory_ids=["a", "b"],
            summary="s",
            detail="d",
            suggested_action="act",
        )
    ]
    d = finding_to_dict(finding)
    assert d == {
        "type": "contradiction",
        "severity": "high",
        "memory_ids": ["a", "b"],
        "summary": "s",
        "detail": "d",
        "suggested_action": "act",
    }


if __name__ == "__main__":
    test_report_sorts_highest_severity_first()
    test_empty_findings_prints_clean_message_without_crashing()
    test_export_json_serializes_enums_to_strings_and_round_trips()
    test_finding_to_dict_matches_export_shape()
    print("Report tests passed.")
