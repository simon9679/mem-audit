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
from datetime import datetime
from typing import Any, Optional


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
            page += 1
        return records

    def _fetch_all_single_page(self, user_id: str, page_size: int) -> list[MemoryRecord]:
        try:
            raw = self._client.get_all(filters={"user_id": user_id}, top_k=page_size)
        except TypeError:
            # Older mem0ai (pre-filters API) — fall back to the legacy signature.
            raw = self._client.get_all(user_id=user_id)

        items = raw.get("results", raw) if isinstance(raw, dict) else raw
        records = [self._normalize(item) for item in items]

        if len(records) == page_size:
            raise RuntimeError(
                f"fetch_all returned exactly page_size={page_size} records for "
                f"user_id={user_id!r}. This client (self-hosted mem0.Memory) has "
                f"no pagination cursor in get_all(), so mem-audit cannot tell "
                f"whether this is the complete memory store or a truncated one. "
                f"An audit over a silently incomplete dataset is worse than no "
                f"audit — re-run with a larger page_size (--page-size) once "
                f"you've confirmed roughly how many memories this user has."
            )
        return records

    def fetch_history(self, memory_id: str) -> list[dict[str, Any]]:
        """Fetch the change history for a single memory (used by staleness detector)."""
        try:
            return self._client.history(memory_id=memory_id)
        except Exception:
            # Some backends/config combos don't have history tracking enabled.
            # Callers should treat an empty list as "no history available",
            # not "this memory was never touched".
            return []

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
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
