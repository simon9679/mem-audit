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
