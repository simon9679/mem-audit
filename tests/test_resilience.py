"""
Offline tests for judge resilience (TZ task 2): 429 retry/backoff, per-pair
skipping when retries are exhausted, incremental partial_out flush, and the
min_request_interval throttle. No network, no openai package required — a
fake exception with status_code=429 duck-types as a rate-limit error.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mem_audit.connectors.mem0_connector import MemoryRecord  # noqa: E402
from mem_audit.detectors.duplicates import CandidatePair  # noqa: E402
from mem_audit.detectors.contradictions import (  # noqa: E402
    find_contradictions,
    retry_on_rate_limit,
)


class FakeRateLimitError(Exception):
    """Duck-types as an HTTP 429 without needing the openai package."""

    def __init__(self, retry_after=None):
        super().__init__("rate limited")
        self.status_code = 429
        if retry_after is not None:
            self.response = _Response({"retry-after": str(retry_after)})


class _Response:
    def __init__(self, headers):
        self.headers = headers
        self.status_code = 429


def _pair(id_a, id_b, text_a="fact a", text_b="fact b"):
    return CandidatePair(
        record_a=MemoryRecord(id=id_a, text=text_a),
        record_b=MemoryRecord(id=id_b, text=text_b),
        similarity=0.9,
    )


def test_retry_recovers_after_two_rate_limits():
    calls = {"n": 0}
    slept = []

    def flaky(prompt):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise FakeRateLimitError()
        return '{"label": "DUPLICATE", "rationale": "same"}'

    wrapped = retry_on_rate_limit(flaky, max_retries=5, sleep=lambda s: slept.append(s))
    findings = find_contradictions([_pair("a", "b")], wrapped)

    assert len(findings) == 1
    assert findings[0].memory_ids == ["a", "b"]
    # Exactly two retries -> exactly two sleeps, exponential 2 then 4.
    assert slept == [2.0, 4.0]


def test_retry_after_header_is_honored():
    slept = []

    def once(prompt):
        if not slept:
            raise FakeRateLimitError(retry_after=30)
        return '{"label": "DUPLICATE", "rationale": "same"}'

    wrapped = retry_on_rate_limit(once, max_retries=3, sleep=lambda s: slept.append(s))
    wrapped("prompt")
    # Slept ~30s (header value) plus a small jitter in [0, 1), not the 2s
    # exponential fallback.
    assert len(slept) == 1
    assert 30.0 <= slept[0] < 31.0


def test_exhausted_retries_skip_pair_and_continue():
    skipped = []

    def always_429(prompt):
        raise FakeRateLimitError()

    good = '{"label": "DUPLICATE", "rationale": "same"}'

    def mixed(prompt):
        # First pair always 429s (after retries -> skip); second pair is fine.
        if "poison" in prompt:
            raise FakeRateLimitError()
        return good

    wrapped = retry_on_rate_limit(mixed, max_retries=2, sleep=lambda s: None)
    pairs = [
        _pair("p1", "p2", text_a="poison", text_b="poison"),
        _pair("q1", "q2"),
    ]
    findings = find_contradictions(
        pairs, wrapped, on_skip=lambda p: skipped.append(p), sleep=lambda s: None
    )

    # Poisoned pair skipped, the good pair still processed, run completed.
    assert len(skipped) == 1
    assert len(findings) == 1
    assert findings[0].memory_ids == ["q1", "q2"]


def test_partial_out_written_after_each_pair(tmp_path=None):
    # Simulate an interruption after k pairs: the (k+1)th judge call raises a
    # non-rate-limit error, which propagates — the file must already hold k.
    import tempfile
    import os

    out = os.path.join(tempfile.mkdtemp(), "partial.json")
    good = '{"label": "DUPLICATE", "rationale": "same"}'

    def judge(prompt):
        if "boom" in prompt:
            raise KeyboardInterrupt("simulated Ctrl-C mid-run")
        return good

    pairs = [
        _pair("a1", "a2"),
        _pair("b1", "b2"),
        _pair("c1", "c2", text_a="boom", text_b="boom"),  # interrupts here
    ]

    raised = False
    try:
        find_contradictions(pairs, judge, partial_out=out)
    except KeyboardInterrupt:
        raised = True
    assert raised

    with open(out, encoding="utf-8") as fh:
        data = json.load(fh)
    # Two pairs completed before the interrupt -> exactly two valid results.
    assert len(data) == 2
    assert {tuple(item["memory_ids"]) for item in data} == {("a1", "a2"), ("b1", "b2")}


def test_report_metadata_tracks_verdicts_and_writes_object():
    import json as _json
    import os
    import tempfile

    out = os.path.join(tempfile.mkdtemp(), "partial.json")
    meta = {"tool": "mem-audit"}

    def judge(prompt):
        # The near-miss pair's text is "unrel"; the judge calls it UNRELATED
        # (which yields no Finding). The other pair is a DUPLICATE.
        if "unrel" in prompt:
            return '{"label": "UNRELATED", "rationale": "false positive"}'
        return '{"label": "DUPLICATE", "rationale": "same"}'

    pairs = [_pair("a", "b"), _pair("c", "d", text_a="unrel", text_b="unrel")]
    findings = find_contradictions(pairs, judge, partial_out=out, report_metadata=meta)

    # Verdict tally covers all four labels + skipped, counted per judged pair.
    assert meta["judge_verdicts"] == {
        "DUPLICATE": 1, "CONTRADICTION": 0, "UPDATE": 0, "UNRELATED": 1, "skipped": 0
    }
    assert len(findings) == 1  # UNRELATED produced no Finding

    # The partial file is the self-describing object, valid JSON, no keys.
    with open(out, encoding="utf-8") as fh:
        data = _json.load(fh)
    assert isinstance(data, dict)
    assert data["metadata"]["judge_verdicts"]["UNRELATED"] == 1
    assert len(data["findings"]) == 1


def test_interrupted_run_leaves_valid_metadata_object():
    import json as _json
    import os
    import tempfile

    out = os.path.join(tempfile.mkdtemp(), "partial.json")
    meta = {"tool": "mem-audit"}
    good = '{"label": "DUPLICATE", "rationale": "same"}'

    def judge(prompt):
        if "boom" in prompt:
            raise KeyboardInterrupt("simulated Ctrl-C")
        return good

    pairs = [_pair("a1", "a2"), _pair("b1", "b2"), _pair("c1", "c2", text_a="boom", text_b="boom")]
    raised = False
    try:
        find_contradictions(pairs, judge, partial_out=out, report_metadata=meta)
    except KeyboardInterrupt:
        raised = True
    assert raised

    with open(out, encoding="utf-8") as fh:
        data = _json.load(fh)  # must be valid despite the interrupt
    assert isinstance(data, dict)
    assert len(data["findings"]) == 2  # two pairs completed before the interrupt
    assert data["metadata"]["judge_verdicts"]["DUPLICATE"] == 2


def test_min_request_interval_zero_adds_no_sleep():
    slept = []
    good = '{"label": "UNRELATED", "rationale": "no"}'
    pairs = [_pair("a", "b"), _pair("c", "d")]
    find_contradictions(
        pairs, lambda p: good, min_request_interval=0.0, sleep=lambda s: slept.append(s)
    )
    assert slept == []


def test_min_request_interval_sleeps_between_calls_only():
    slept = []
    good = '{"label": "UNRELATED", "rationale": "no"}'
    pairs = [_pair("a", "b"), _pair("c", "d"), _pair("e", "f")]
    find_contradictions(
        pairs, lambda p: good, min_request_interval=12.0, sleep=lambda s: slept.append(s)
    )
    # 3 pairs -> sleep before pairs 2 and 3 only (not before the first).
    assert slept == [12.0, 12.0]


if __name__ == "__main__":
    test_retry_recovers_after_two_rate_limits()
    test_retry_after_header_is_honored()
    test_exhausted_retries_skip_pair_and_continue()
    test_partial_out_written_after_each_pair()
    test_report_metadata_tracks_verdicts_and_writes_object()
    test_interrupted_run_leaves_valid_metadata_object()
    test_min_request_interval_zero_adds_no_sleep()
    test_min_request_interval_sleeps_between_calls_only()
    print("Resilience tests passed.")
