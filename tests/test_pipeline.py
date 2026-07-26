import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))

from demo_offline import FAKE_MEMORIES, FakeMem0Client, fake_embed_fn, fake_llm_judge  # noqa: E402
from mem_audit.detectors.base import FindingType, Severity  # noqa: E402
from mem_audit.pipeline import run_audit  # noqa: E402


def test_finds_the_4896_contradiction():
    client = FakeMem0Client(FAKE_MEMORIES)
    findings, total = run_audit(
        mem0_client=client,
        user_id="demo",
        embed_fn=fake_embed_fn,
        llm_call=fake_llm_judge,
        min_similarity=0.30,
    )

    assert total == 9

    contradictions = [f for f in findings if f.type == FindingType.CONTRADICTION]
    assert len(contradictions) == 1
    assert contradictions[0].severity == Severity.HIGH
    assert {"m1", "m2"} == set(contradictions[0].memory_ids)


def test_finds_the_stale_update():
    client = FakeMem0Client(FAKE_MEMORIES)
    findings, _ = run_audit(
        mem0_client=client,
        user_id="demo",
        embed_fn=fake_embed_fn,
        llm_call=fake_llm_judge,
        min_similarity=0.30,
    )
    stale = [f for f in findings if f.type == FindingType.STALE]
    assert len(stale) == 1
    assert {"m3", "m4"} == set(stale[0].memory_ids)


def test_finds_the_duplicate():
    client = FakeMem0Client(FAKE_MEMORIES)
    findings, _ = run_audit(
        mem0_client=client,
        user_id="demo",
        embed_fn=fake_embed_fn,
        llm_call=fake_llm_judge,
        min_similarity=0.30,
    )
    dups = [f for f in findings if f.type == FindingType.DUPLICATE]
    assert len(dups) == 1
    assert {"m5", "m6"} == set(dups[0].memory_ids)


def test_unrelated_pair_does_not_leak_into_findings():
    """
    Regression test for the bug found in review: a pair the embedding pass
    flags as close (m8, m9) but the LLM judge calls UNRELATED must produce
    NO finding at all — not a duplicate, not anything. Before the fix, the
    cheap pass's own Finding survived regardless of what the judge said.
    """
    client = FakeMem0Client(FAKE_MEMORIES)
    findings, _ = run_audit(
        mem0_client=client,
        user_id="demo",
        embed_fn=fake_embed_fn,
        llm_call=fake_llm_judge,
        min_similarity=0.30,
    )
    flagged_ids = {mid for f in findings for mid in f.memory_ids}
    assert "m8" not in flagged_ids
    assert "m9" not in flagged_ids


def test_unrelated_memory_produces_no_findings():
    client = FakeMem0Client(FAKE_MEMORIES)
    findings, _ = run_audit(
        mem0_client=client,
        user_id="demo",
        embed_fn=fake_embed_fn,
        llm_call=fake_llm_judge,
        min_similarity=0.30,
    )
    flagged_ids = {mid for f in findings for mid in f.memory_ids}
    assert "m7" not in flagged_ids  # "I work as a nurse" — no close pair


def test_no_crash_on_single_memory():
    client = FakeMem0Client(FAKE_MEMORIES[:1])
    findings, total = run_audit(
        mem0_client=client,
        user_id="demo",
        embed_fn=fake_embed_fn,
        llm_call=fake_llm_judge,
    )
    assert findings == []
    assert total == 1


def test_run_audit_populates_report_metadata():
    """run_audit fills the passed metadata dict with the run's counts/verdicts."""
    meta = {}
    client = FakeMem0Client(FAKE_MEMORIES)
    findings, total = run_audit(
        mem0_client=client,
        user_id="demo",
        embed_fn=fake_embed_fn,
        llm_call=fake_llm_judge,
        min_similarity=0.30,
        report_metadata=meta,
    )
    assert meta["memories_scanned"] == total == 9
    assert meta["candidate_pairs"] >= len(findings)
    verdicts = meta["judge_verdicts"]
    assert set(verdicts) == {"DUPLICATE", "CONTRADICTION", "UPDATE", "UNRELATED", "skipped"}
    # Every candidate pair was judged exactly once (no rate-limit skips here).
    assert sum(verdicts.values()) == meta["candidate_pairs"]
    assert verdicts["skipped"] == 0


def test_run_audit_metadata_on_tiny_store():
    """< 2 memories: metadata still gets scanned count, zero pairs, zeroed verdicts."""
    meta = {}
    findings, total = run_audit(
        mem0_client=FakeMem0Client(FAKE_MEMORIES[:1]),
        user_id="demo",
        embed_fn=fake_embed_fn,
        llm_call=fake_llm_judge,
        report_metadata=meta,
    )
    assert findings == [] and total == 1
    assert meta["memories_scanned"] == 1
    assert meta["candidate_pairs"] == 0
    assert sum(meta["judge_verdicts"].values()) == 0


def test_raises_when_oss_client_hits_page_size_ceiling():
    """
    Regression test: a self-hosted (non-MemoryClient) client that returns
    exactly page_size results must raise, not silently under-report. This
    replaces the old warnings.warn-based behavior, which was easy to miss
    in a CLI tool people run once and read the table from.
    """
    client = FakeMem0Client(FAKE_MEMORIES)
    try:
        run_audit(
            mem0_client=client,
            user_id="demo",
            embed_fn=fake_embed_fn,
            llm_call=fake_llm_judge,
            page_size=len(FAKE_MEMORIES),  # exactly matches -> looks truncated
        )
        raised = False
    except RuntimeError:
        raised = True
    assert raised, "expected RuntimeError when records returned == page_size"


if __name__ == "__main__":
    test_finds_the_4896_contradiction()
    test_finds_the_stale_update()
    test_finds_the_duplicate()
    test_unrelated_pair_does_not_leak_into_findings()
    test_unrelated_memory_produces_no_findings()
    test_no_crash_on_single_memory()
    test_run_audit_populates_report_metadata()
    test_run_audit_metadata_on_tiny_store()
    test_raises_when_oss_client_hits_page_size_ceiling()
    print("All tests passed.")


def test_naive_aware_datetime_mix_does_not_crash():
    """
    Regression test for a real bug found via external review + reproduced
    manually: if one record's created_at is a naive datetime and another's
    is timezone-aware, comparing them with `>` used to raise TypeError and
    crash the whole judge_pair call. Fixed by normalizing naive datetimes
    to UTC in Mem0Connector._parse_dt.
    """
    from datetime import datetime, timezone
    from mem_audit.connectors.mem0_connector import _parse_dt

    aware = _parse_dt("2026-07-01T12:00:00Z")
    naive_input = datetime(2026, 7, 2, 12, 0, 0)
    normalized = _parse_dt(naive_input)

    assert aware.tzinfo is not None
    assert normalized.tzinfo is not None
    # must not raise TypeError
    assert aware < normalized


def test_mismatched_embedding_count_raises_clear_error():
    """
    Regression test: an embed_fn that returns fewer vectors than input
    texts (simulating a provider partial failure) must raise a clear
    ValueError, not silently misalign records[i] with the wrong vector.
    """
    import numpy as np
    from mem_audit.connectors.mem0_connector import MemoryRecord
    from mem_audit.detectors.duplicates import find_duplicate_candidates

    records = [
        MemoryRecord(id="a", text="fact one"),
        MemoryRecord(id="b", text="fact two"),
        MemoryRecord(id="c", text="fact three"),
    ]

    def broken_embed_fn(texts):
        # returns one fewer vector than requested
        return np.random.randn(len(texts) - 1, 8).astype(np.float32)

    raised = False
    try:
        find_duplicate_candidates(records, broken_embed_fn)
    except ValueError:
        raised = True
    assert raised, "expected ValueError on embedding count mismatch"


def test_clip_leaves_short_text_untouched():
    """Text within the limit is returned verbatim, with no ellipsis."""
    from mem_audit.detectors.contradictions import _clip

    short = "I live in Berlin"
    assert _clip(short, limit=60) == short
    assert "…" not in _clip(short, limit=60)


def test_clip_breaks_long_text_on_a_word_boundary():
    """Long text is trimmed back to the last whole word, plus an ellipsis."""
    from mem_audit.detectors.contradictions import _clip

    text = "My commute eats up close to an hour, one direction, every single day"
    out = _clip(text, limit=40)
    assert out.endswith("…")
    body = out[:-1]
    # Never longer than the limit, and never cut mid-word (the char right
    # after the kept prefix in the original was a space).
    assert len(body) <= 40
    assert text.startswith(body)
    assert text[len(body)] == " "


def test_clip_handles_text_with_no_spaces():
    """A long unbroken token (e.g. a URL) must not break the helper or return empty."""
    from mem_audit.detectors.contradictions import _clip

    url = "https://example.com/" + "a" * 200
    out = _clip(url, limit=60)
    assert out.endswith("…")
    assert out[:-1] == url[:60]
    assert len(out[:-1]) == 60


if __name__ == "__main__":
    test_naive_aware_datetime_mix_does_not_crash()
    test_mismatched_embedding_count_raises_clear_error()
    test_clip_leaves_short_text_untouched()
    test_clip_breaks_long_text_on_a_word_boundary()
    test_clip_handles_text_with_no_spaces()
    print("Additional regression tests passed.")
