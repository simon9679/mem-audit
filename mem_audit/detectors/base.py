from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FindingType(str, Enum):
    DUPLICATE = "duplicate"
    CONTRADICTION = "contradiction"
    STALE = "stale"
    PERSONA_DRIFT = "persona_drift"


class Severity(str, Enum):
    LOW = "low"          # likely harmless, informational
    MEDIUM = "medium"     # probably worth a look
    HIGH = "high"         # likely to cause visible bad behavior (e.g. contradicting facts)


@dataclass
class Finding:
    type: FindingType
    severity: Severity
    memory_ids: list[str]
    summary: str          # one-line human-readable description
    detail: str = ""       # optional longer explanation (e.g. LLM-judge rationale)
    suggested_action: str = ""  # e.g. "keep newer, delete older" — never applied automatically


def finding_to_dict(finding: "Finding") -> dict:
    """
    JSON-serializable view of a Finding, with enums flattened to their string
    values. Kept here (rather than in report.py) so the incremental partial
    writer in the contradictions detector can reuse it without pulling in rich.
    """
    type_value = finding.type.value if hasattr(finding.type, "value") else finding.type
    severity_value = finding.severity.value if hasattr(finding.severity, "value") else finding.severity
    return {
        "type": type_value,
        "severity": severity_value,
        "memory_ids": list(finding.memory_ids),
        "summary": finding.summary,
        "detail": finding.detail,
        "suggested_action": finding.suggested_action,
    }
