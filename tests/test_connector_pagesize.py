"""
Tests for the fetch_all silent-truncation guard, including the legacy
get_all() fallback path (TZ follow-up: the fallback used to drop page_size and
silently read only mem0's default first page).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mem_audit.connectors.mem0_connector import (  # noqa: E402
    _MAX_PAGES,
    _MEM0_LEGACY_DEFAULT_LIMIT,
    Mem0Connector,
)


def _rows(n, user_id="u"):
    return [{"id": "m%d" % i, "memory": "fact %d" % i, "user_id": user_id} for i in range(n)]


class ModernClient:
    """Accepts filters/top_k (current mem0 signature)."""

    def __init__(self, total):
        self._total = total

    def get_all(self, filters=None, top_k=500, **kwargs):
        uid = (filters or {}).get("user_id")
        return {"results": _rows(min(self._total, top_k), uid)}


class LegacyLimitClient:
    """No filters/top_k, but the legacy get_all() DOES accept a limit."""

    def __init__(self, total):
        self._total = total

    def get_all(self, *args, **kwargs):
        if "filters" in kwargs or "top_k" in kwargs:
            raise TypeError("legacy get_all has no filters/top_k")
        if "limit" in kwargs:
            uid = kwargs.get("user_id")
            return {"results": _rows(min(self._total, kwargs["limit"]), uid)}
        raise TypeError("must pass limit")


class LegacyNoLimitClient:
    """Oldest path: bare get_all(user_id=...) only, capped at the default limit."""

    def __init__(self, total):
        self._total = total

    def get_all(self, *args, **kwargs):
        if "filters" in kwargs or "top_k" in kwargs:
            raise TypeError("no filters/top_k")
        if "limit" in kwargs:
            raise TypeError("no limit either")
        uid = kwargs.get("user_id")
        # mem0's own default page cap applies.
        return {"results": _rows(min(self._total, _MEM0_LEGACY_DEFAULT_LIMIT), uid)}


class NeverTerminatingCursorClient:
    """
    Platform-style client whose cursor never ends: every page reports a
    non-null `next`. Simulates a broken/looping API. Used to exercise the
    pagination circuit breaker directly (the classifier would treat a bare
    fake as 'oss' when mem0 isn't installed, so we call the paginated method
    itself).
    """

    def __init__(self):
        self.calls = 0

    def get_all(self, filters=None, page=1, page_size=500, **kwargs):
        self.calls += 1
        uid = (filters or {}).get("user_id")
        return {"results": _rows(1, uid), "next": "cursor", "previous": None}


def _raises_runtime(fn):
    try:
        fn()
        return False
    except RuntimeError:
        return True


# -- modern path (unchanged behavior) --------------------------------------- #
def test_modern_client_reads_all_below_page_size():
    recs = Mem0Connector(ModernClient(50)).fetch_all(user_id="u", page_size=500)
    assert len(recs) == 50


def test_modern_client_raises_at_page_size_ceiling():
    assert _raises_runtime(lambda: Mem0Connector(ModernClient(500)).fetch_all(user_id="u", page_size=500))


# -- legacy WITH limit: page_size is honored, ceiling guard still applies ---- #
def test_legacy_limit_reads_full_store_when_below_page_size():
    # 250 records, page_size 500 -> limit forwarded, all 250 returned, no raise.
    recs = Mem0Connector(LegacyLimitClient(250)).fetch_all(user_id="u", page_size=500)
    assert len(recs) == 250


def test_legacy_limit_raises_when_hitting_page_size():
    # More than page_size available -> limit clamps to exactly page_size -> looks
    # truncated -> raise (the fix forwards page_size instead of dropping it).
    assert _raises_runtime(lambda: Mem0Connector(LegacyLimitClient(999)).fetch_all(user_id="u", page_size=200))


# -- legacy WITHOUT limit: must not silently under-read at the default cap --- #
def test_legacy_no_limit_raises_at_default_cap():
    # 300 records exist but the bare call caps at 100 -> silent under-read used
    # to happen here; now it must raise.
    assert _raises_runtime(
        lambda: Mem0Connector(LegacyNoLimitClient(300)).fetch_all(user_id="u", page_size=500)
    )


def test_legacy_no_limit_ok_when_store_smaller_than_cap():
    # Genuinely small store (< default cap) -> real complete read, no raise.
    recs = Mem0Connector(LegacyNoLimitClient(42)).fetch_all(user_id="u", page_size=500)
    assert len(recs) == 42


# -- paginated (Platform) path: never-ending cursor must not loop forever ---- #
def test_paginated_never_terminating_cursor_raises_at_page_ceiling():
    client = NeverTerminatingCursorClient()
    conn = Mem0Connector(client)
    # Call the paginated method directly: without mem0 installed, the client
    # classifier would route a fake to the single-page path.
    assert _raises_runtime(lambda: conn._fetch_all_paginated(user_id="u", page_size=500))
    # It bailed at the page ceiling instead of spinning forever.
    assert client.calls <= _MAX_PAGES + 1


if __name__ == "__main__":
    test_modern_client_reads_all_below_page_size()
    test_modern_client_raises_at_page_size_ceiling()
    test_legacy_limit_reads_full_store_when_below_page_size()
    test_legacy_limit_raises_when_hitting_page_size()
    test_legacy_no_limit_raises_at_default_cap()
    test_legacy_no_limit_ok_when_store_smaller_than_cap()
    test_paginated_never_terminating_cursor_raises_at_page_ceiling()
    print("Connector page_size guard tests passed.")
