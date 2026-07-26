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


def test_equal_timestamps_order_deterministically_by_id():
    """
    Two records with identical, non-empty created_at must produce the SAME
    prompt regardless of the order they're handed to judge_pair. Before the
    fix the id tiebreaker lived in an `elif` that only ran when a created_at
    was missing, so equal timestamps left the pair in connector order — and
    the assembled prompt flipped depending on input order.
    """
    ts = datetime(2026, 2, 2, 9, 30, tzinfo=timezone.utc)
    a = MemoryRecord(id="m1", text="I live in Berlin", created_at=ts)
    b = MemoryRecord(id="m2", text="I live in Madrid", created_at=ts)

    prompt_ab = _capture_prompt(a, b)
    prompt_ba = _capture_prompt(b, a)

    assert prompt_ab == prompt_ba
    # And the deterministic order is by id, so the lower id ("m1", Berlin) is
    # the "older" slot in both.
    assert prompt_ab.index("Berlin") < prompt_ab.index("Madrid")


if __name__ == "__main__":
    test_dates_appear_in_prompt_when_present()
    test_no_date_line_when_both_dates_missing()
    test_partial_dates_only_label_the_record_that_has_one()
    test_equal_timestamps_order_deterministically_by_id()
    print("Judge prompt date tests passed.")
