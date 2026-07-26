"""
Thin read-only wrapper around the Mem0 SDK.

Design decision: we never touch Qdrant/pgvector/etc. directly. Mem0 exposes
a stable client API (get_all, history, search) that works identically
regardless of the configured vector_store backend. This keeps mem-audit
backend-agnostic for free — the same code works whether the user runs
Qdrant, pgvector, Chroma, or anything else Mem0 supports.

We are read-only by construction: this module has no update/delete calls.
Fixes (if the user opts into them) are applied by a separate, explicit
module — never silently by the connector.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# mem0's legacy get_all() (the pre-filters signature, no top_k/limit) applies a
# small default page cap when no limit is passed. Observed as 100 on the
# self-hosted mem0.Memory path; used only as a conservative "did we hit the
# default cap?" tripwire, never to bound the read itself.
_MEM0_LEGACY_DEFAULT_LIMIT = 100

# Circuit breakers for the cursor-based (Platform) pagination loop. It exits
# normally when `next` goes falsy; these bound the damage if a stuck/broken API
# keeps returning a truthy `next` forever, which would otherwise be an
# unbounded stream of requests to a paid service. Two independent ceilings —
# one on pages followed, one on total records accumulated — so neither a
# never-ending cursor nor a client returning huge pages can run away. Both are
# far above any realistic personal memory store.
_MAX_PAGES = 1_000
_MAX_RECORDS = 1_000_000


@dataclass
class MemoryRecord:
    """Normalized view of a single Mem0 memory, independent of backend quirks."""

    id: str
    text: str
    user_id: Optional[str] = None
    categories: list[str] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)  # original payload, for debugging


class Mem0Connector:
    """
    Wraps a `mem0.Memory` (or `mem0.MemoryClient`) instance.

    Usage:
        from mem0 import Memory
        m = Memory.from_config(config)
        connector = Mem0Connector(m)
        records = connector.fetch_all(user_id="alice")
    """

    def __init__(self, mem0_client: Any):
        self._client = mem0_client

    def fetch_all(self, user_id: str, page_size: int = 500) -> list[MemoryRecord]:
        """
        Fetch every memory for a given user_id as normalized records.

        Two real, verified constraints on mem0ai==2.0.12 drive this method:

        1. get_all() takes filters={"user_id": ...}, not a top-level user_id
           kwarg — the old call raises ValueError. We call with the current
           signature and fall back to the legacy one for older installs.

        2. Pagination differs by client class:
           - `MemoryClient` (hosted Platform API) supports real cursor-based
             pagination: passing page/page_size returns
             {"count", "next", "previous", "results"}, and we follow `next`
             until it's null.
           - `Memory` (self-hosted OSS, e.g. Qdrant/pgvector backends) has
             NO pagination — get_all() only accepts top_k, backed by
             `vector_store.list(filters, top_k)` with a hard limit and no
             cursor. If a user has more memories than page_size, there is
             no way to page through the rest. We refuse to silently return
             a partial result: a confident report over 25% of someone's
             memory store is worse than no report, so we raise instead of
             warning.
        """
        client_kind = self._classify_client()

        if client_kind == "platform":
            return self._fetch_all_paginated(user_id, page_size)
        return self._fetch_all_single_page(user_id, page_size)

    def _classify_client(self) -> str:
        """Returns "platform" (MemoryClient, real cursor) or "oss" (Memory, no cursor)."""
        try:
            from mem0 import MemoryClient

            if isinstance(self._client, MemoryClient):
                return "platform"
        except ImportError:
            pass
        return "oss"

    def _fetch_all_paginated(self, user_id: str, page_size: int) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        page = 1
        while True:
            raw = self._client.get_all(filters={"user_id": user_id}, page=page, page_size=page_size)
            results = raw.get("results", []) if isinstance(raw, dict) else raw
            records.extend(self._normalize(item) for item in results)
            if not isinstance(raw, dict) or not raw.get("next"):
                break
            # Circuit breakers: a broken/looping API that always reports a
            # truthy `next` would page forever, hammering a paid service. Refuse
            # loudly rather than warn — an audit that never terminates is worse
            # than no audit.
            if len(records) >= _MAX_RECORDS:
                raise RuntimeError(
                    f"fetch_all accumulated {len(records)} records for "
                    f"user_id={user_id!r} and the paginated client is still "
                    f"reporting more (non-null 'next'), past the {_MAX_RECORDS} "
                    f"record safety ceiling. This is almost certainly a broken or "
                    f"looping API response rather than a genuinely enormous store. "
                    f"Aborting rather than issuing unbounded requests — if the "
                    f"store really is this large, mem-audit is the wrong tool for "
                    f"it (it is O(n^2); see the README scope note)."
                )
            page += 1
            if page > _MAX_PAGES:
                raise RuntimeError(
                    f"fetch_all followed more than {_MAX_PAGES} pages for "
                    f"user_id={user_id!r} (page_size={page_size}) without the "
                    f"cursor terminating. The paginated client kept returning a "
                    f"non-null 'next' — almost certainly a broken or looping API "
                    f"response rather than a genuinely huge store. Aborting rather "
                    f"than issuing unbounded requests; re-check the client/endpoint "
                    f"if you believe this user really has that many memories."
                )
        return records

    def _fetch_all_single_page(self, user_id: str, page_size: int) -> list[MemoryRecord]:
        limit_enforced = True
        try:
            raw = self._client.get_all(filters={"user_id": user_id}, top_k=page_size)
        except TypeError:
            # Older mem0ai (pre-filters API). Still try to bound the read by
            # passing an explicit limit into the legacy signature — otherwise
            # mem0's get_all() applies its own small default page cap (observed:
            # 100) and we'd silently audit only the first page. A confident
            # report over an unknown fraction of the store is worse than none.
            try:
                raw = self._client.get_all(user_id=user_id, limit=page_size)
            except TypeError:
                # This version doesn't accept a limit at all, so we cannot bound
                # the read: mem0's own default cap decides how many come back.
                raw = self._client.get_all(user_id=user_id)
                limit_enforced = False

        items = raw.get("results", raw) if isinstance(raw, dict) else raw
        records = [self._normalize(item) for item in items]

        # Silent-truncation guard. The reader must either get everything or a
        # loud error — a quietly partial result is never acceptable.
        if limit_enforced and len(records) == page_size:
            # We asked for page_size and got exactly that back: indistinguishable
            # from a truncated page on a client with no pagination cursor.
            raise RuntimeError(
                f"fetch_all returned exactly page_size={page_size} records for "
                f"user_id={user_id!r}. This client (self-hosted mem0.Memory) has "
                f"no pagination cursor in get_all(), so mem-audit cannot tell "
                f"whether this is the complete memory store or a truncated one. "
                f"An audit over a silently incomplete dataset is worse than no "
                f"audit — re-run with a larger page_size (--page-size) once "
                f"you've confirmed roughly how many memories this user has."
            )
        if not limit_enforced and len(records) == _MEM0_LEGACY_DEFAULT_LIMIT:
            # We could not bound the read and got back exactly mem0's default
            # cap — almost certainly a truncated first page, and even if the
            # store really has this many, we cannot prove it. Refuse rather
            # than under-report.
            raise RuntimeError(
                f"fetch_all read exactly {len(records)} records for "
                f"user_id={user_id!r} via mem0's legacy get_all(), which caps at "
                f"its default page size ({_MEM0_LEGACY_DEFAULT_LIMIT}) and does "
                f"not accept a limit on this mem0ai version. mem-audit cannot "
                f"tell the full store from a truncated first page and refuses to "
                f"audit a silently partial dataset. Upgrade mem0ai to a version "
                f"whose get_all() accepts filters/top_k (so the page size is "
                f"controllable), or confirm this user really has "
                f"<{_MEM0_LEGACY_DEFAULT_LIMIT} memories."
            )
        return records

    @staticmethod
    def _normalize(item: dict[str, Any]) -> MemoryRecord:
        text = item.get("memory") or item.get("text") or item.get("data") or ""
        created = _parse_dt(item.get("created_at"))
        updated = _parse_dt(item.get("updated_at"))
        return MemoryRecord(
            id=str(item.get("id", "")),
            text=text,
            user_id=item.get("user_id"),
            categories=item.get("categories") or [],
            created_at=created,
            updated_at=updated,
            metadata=item.get("metadata") or {},
            raw=item,
        )


def _parse_dt(value: Any) -> Optional[datetime]:
    """
    Normalizes to a timezone-aware datetime, or None.

    Verified real bug: if one record's created_at arrives as a naive
    datetime object (some backends return these directly) and another's
    as an ISO string with a timezone (e.g. "...Z"), comparing them with
    `>` in contradictions.judge_pair raises TypeError: can't compare
    offset-naive and offset-aware datetimes — crashing the whole audit.
    Fixed by always attaching UTC to naive values here, at the source,
    rather than trying to guard every comparison site downstream.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None
