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
    test_raises_when_oss_client_hits_page_size_ceiling()
    print("All tests passed.")
