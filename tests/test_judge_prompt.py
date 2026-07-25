"""
Offline tests for the date-aware judge prompt (TZ task 3). A spy llm_call
captures the exact prompt judge_pair assembles so we can assert on the dates.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mem_audit.connectors.mem0_connector import MemoryRecord  # noqa: E402
from mem_audit.detectors.contradictions import judge_pair  # noqa: E402


def _capture_prompt(record_a, record_b):
    captured = {}

    def spy(prompt):
        captured["prompt"] = prompt
        return '{"label": "UNRELATED", "rationale": "n/a"}'

    judge_pair(record_a, record_b, spy)
    return captured["prompt"]


def test_dates_appear_in_prompt_when_present():
    a = MemoryRecord(id="1", text="I live in Berlin",
                     created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    b = MemoryRecord(id="2", text="I live in Madrid",
                     created_at=datetime(2028, 3, 15, tzinfo=timezone.utc))
    prompt = _capture_prompt(a, b)

    assert "2026-01-01" in prompt
    assert "2028-03-15" in prompt
    # Date-only, no time component leaking in.
    assert "00:00" not in prompt


def test_no_date_line_when_both_dates_missing():
    a = MemoryRecord(id="1", text="fact one")
    b = MemoryRecord(id="2", text="fact two")
    prompt = _capture_prompt(a, b)

    assert "older" in prompt
    assert "newer" in prompt
    assert "unknown" not in prompt.lower()
    # No "older, <date>" — the label is bare when there's no date.
    assert "older," not in prompt
    assert "newer," not in prompt


def test_partial_dates_only_label_the_record_that_has_one():
    a = MemoryRecord(id="1", text="older fact",
                     created_at=datetime(2026, 5, 20, tzinfo=timezone.utc))
    b = MemoryRecord(id="2", text="newer fact")  # no date
    prompt = _capture_prompt(a, b)

    assert "older, 2026-05-20" in prompt
    assert "unknown" not in prompt.lower()
    # B has no date, so its label stays bare.
    assert "newer, " not in prompt
    assert '(newer):' in prompt


if __name__ == "__main__":
    test_dates_appear_in_prompt_when_present()
    test_no_date_line_when_both_dates_missing()
    test_partial_dates_only_label_the_record_that_has_one()
    print("Judge prompt date tests passed.")
