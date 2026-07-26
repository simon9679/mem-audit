from __future__ import annotations

import json
import os
import random
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from mem_audit.connectors.mem0_connector import MemoryRecord
from mem_audit.detectors.base import Finding, FindingType, Severity, finding_to_dict
from mem_audit.detectors.duplicates import CandidatePair

# Classifier contract: given two memory texts, return one of these labels.
# This directly targets the failure mode documented in mem0ai/mem0#4896 and
# #4536 — near-duplicate ADD events that should have been UPDATE/DELETE but
# weren't, because Mem0's ADD-only extraction doesn't resolve them.
_LABELS = {"DUPLICATE", "CONTRADICTION", "UPDATE", "UNRELATED"}

_JUDGE_PROMPT = """You are auditing an AI agent's long-term memory store for consistency.
You will see two memory entries about the same user. Classify their relationship.

Memory A ({label_a}): "{text_a}"
Memory B ({label_b}): "{text_b}"

Respond with strict JSON only, no other text:
{{
  "label": "DUPLICATE" | "CONTRADICTION" | "UPDATE" | "UNRELATED",
  "rationale": "<one short sentence>"
}}

Label meanings:
- DUPLICATE: both say the same thing, no new information in B.
- CONTRADICTION: A and B cannot both be true at the same time (e.g. two different
  cities as "current home"), and it's not a case of B simply superseding A over time.
- UPDATE: B is a natural evolution of A (e.g. changed job, moved city) — this is
  expected drift, not a bug, but worth surfacing so a human can confirm A should
  be retired.
- UNRELATED: the embedding similarity was a false positive; A and B are not
  actually about the same fact.

The gap between CONTRADICTION and UPDATE often hinges on the time between the two
memories: a large gap between the dates leans toward UPDATE (the fact changed over
time), while the same or a very close date leans toward CONTRADICTION (both claimed
to be true at once). Use the dates shown above when they are present."""


@dataclass
class JudgeResult:
    label: str
    rationale: str


LLMCallFn = Callable[[str], str]  # prompt -> raw text completion

DEFAULT_MAX_RETRIES = 5


def _retry_after_seconds(exc: BaseException) -> Optional[float]:
    """
    Pull a `retry-after` hint (in seconds) out of a rate-limit error if one is
    present, else None.

    GitHub Models in particular returns a real `retry-after` header on 429
    (observed values in the tens of thousands of seconds for the daily
    `UserByModelByDay` quota), so honoring it matters — a fixed sleep can't.
    We look at both the exception's own attributes and the underlying HTTP
    response headers, since openai-python surfaces these in different places
    across versions and compatible clients.
    """
    # Some clients attach retry_after / retry-after directly to the exception.
    for attr in ("retry_after", "retry_after_seconds"):
        value = getattr(exc, attr, None)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass

    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        for key in ("retry-after", "Retry-After"):
            try:
                value = headers.get(key)
            except AttributeError:
                value = None
            if value:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
    return None


def _is_rate_limit_error(exc: BaseException) -> bool:
    """
    True if `exc` looks like an HTTP 429 / rate-limit error, without hard-
    depending on openai being importable.

    We check openai.RateLimitError when openai is available, and otherwise
    (or additionally) fall back to a status_code == 429 duck-type — which
    also covers custom OpenAI-compatible clients and makes this testable
    without constructing a real openai error.
    """
    try:
        import openai

        if isinstance(exc, openai.RateLimitError):
            return True
    except ImportError:
        pass

    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return status == 429


def retry_on_rate_limit(
    call: LLMCallFn,
    max_retries: int = DEFAULT_MAX_RETRIES,
    sleep: Callable[[float], None] = time.sleep,
) -> LLMCallFn:
    """
    Wraps a judge `call(prompt) -> str` with retry-on-429 and exponential
    backoff.

    On a rate-limit error we sleep and retry up to `max_retries` times. If the
    error carries a `retry-after` hint we honor it exactly (plus a little
    jitter); otherwise we back off exponentially (2, 4, 8, 16, 32s). Any non-
    rate-limit error propagates immediately. After the retries are exhausted
    the last rate-limit error is re-raised — find_contradictions turns that
    into a skipped pair rather than a crashed run.

    Exposed as a standalone helper so a user's own custom `llm_call` can opt
    into the same behavior (`retry_on_rate_limit(my_call)`) without being
    forced to.
    """

    def wrapped(prompt: str) -> str:
        attempt = 0
        while True:
            try:
                return call(prompt)
            except Exception as exc:  # noqa: BLE001 — re-raised unless it's a rate limit
                if not _is_rate_limit_error(exc):
                    raise
                attempt += 1
                if attempt > max_retries:
                    raise
                retry_after = _retry_after_seconds(exc)
                if retry_after is not None:
                    delay = retry_after + random.uniform(0.0, 1.0)
                else:
                    delay = float(2 ** attempt)  # 2, 4, 8, 16, 32, ...
                sleep(delay)

    return wrapped


def openai_compatible_judge(
    model: str,
    base_url: str | None = None,
    api_key: str | None = None,
    api_key_env: str = "OPENAI_API_KEY",
    max_retries: int = DEFAULT_MAX_RETRIES,
    client=None,
) -> LLMCallFn:
    """
    Returns a judge callable(prompt) -> str backed by any OpenAI-compatible
    chat endpoint. Swap with any callable(prompt) -> str.

    base_url=None uses the openai client library's default endpoint. The key is
    taken from `api_key` if given, else read from the `api_key_env` environment
    variable; a missing key raises ValueError naming that variable. The judge is
    called once per candidate pair, so it is the volume-driving step in the
    pipeline; for endpoints whose binding constraint is requests-per-minute, the
    throughput limiter is min_request_interval plus 429 backoff (see
    find_contradictions and retry_on_rate_limit), not a token budget.

    The returned callable already retries on HTTP 429 with backoff (see
    retry_on_rate_limit); pass max_retries=0 to disable. Pass `client` to inject
    a pre-built OpenAI-compatible client (tests, or a custom transport); when
    given, key resolution is skipped entirely.
    """
    if client is None:
        import os

        # Resolve/validate the key BEFORE importing openai: a missing-key error
        # ("set the X env var") is self-contained and must not depend on the
        # optional openai package being installed (CI runs without it).
        resolved_key = api_key or os.environ.get(api_key_env)
        if not resolved_key:
            raise ValueError(
                f"openai_compatible_judge requires an API key. Pass api_key= "
                f"explicitly or set the {api_key_env} env var."
            )

        import openai

        client = openai.OpenAI(base_url=base_url, api_key=resolved_key)

    def call(prompt: str) -> str:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        # Defensive: a malformed/unexpected provider response (e.g. empty
        # choices) would otherwise raise IndexError/AttributeError and
        # crash the whole audit over one judge call. _safe_parse already
        # treats unparseable text as UNRELATED — extend that same
        # tolerance to a malformed response shape.
        try:
            return resp.choices[0].message.content or ""
        except (IndexError, AttributeError):
            return ""

    return retry_on_rate_limit(call, max_retries=max_retries)


def judge_pair(record_a: MemoryRecord, record_b: MemoryRecord, llm_call: LLMCallFn) -> JudgeResult:
    # Order by created_at when available so "older"/"newer" in the prompt is
    # meaningful; contradiction vs. update hinges on temporal order.
    #
    # Defensive try/except: Mem0Connector._parse_dt normalizes naive
    # datetimes to UTC at the source, but MemoryRecord can in principle be
    # constructed directly (tests, other connectors) with a mix of naive
    # and timezone-aware datetimes, which makes `>` raise TypeError. If
    # that happens, fall back to the pair's original order rather than
    # crashing the whole audit over one unorderable pair.
    a, b = record_a, record_b
    ordered_by_time = False
    if a.created_at and b.created_at:
        try:
            if a.created_at > b.created_at:
                a, b = b, a
            ordered_by_time = a.created_at != b.created_at
        except TypeError:
            # Mixed naive/aware datetimes slipped past _parse_dt (e.g. a
            # MemoryRecord built directly in a test/other connector). Fall
            # back to the id tiebreaker below rather than crashing.
            ordered_by_time = False

    if not ordered_by_time and a.id and b.id:
        # Either no usable created_at, or both timestamps are equal — order is
        # otherwise whatever the connector happened to return, which is not
        # stable across runs/pagination. Fall back to a deterministic
        # tiebreaker (id string) so "older"/"newer" in the prompt is at least
        # consistent run-to-run, even if not temporally meaningful.
        #
        # Same-timestamp collisions are the common real case here: memories
        # added in rapid succession (batch-seeding, migration) can land on the
        # same created_at value depending on the backend's timestamp
        # resolution, so `>` returns False either way and leaves the pair in
        # whatever order the connector returned — not necessarily insertion
        # order.
        if a.id > b.id:
            a, b = b, a

    prompt = _build_judge_prompt(a, b)
    raw = llm_call(prompt)
    parsed = _safe_parse(raw)
    return JudgeResult(label=parsed.get("label", "UNRELATED"), rationale=parsed.get("rationale", ""))


def _date_label(base: str, dt: Optional[datetime]) -> str:
    """
    "older" -> "older, 2026-01-01" when a date is available, or just "older"
    when it isn't. Date only (YYYY-MM-DD), no time, to keep the prompt quiet.
    We never emit "older, unknown" — absence of a date means the plain label.
    """
    if dt is None:
        return base
    return f"{base}, {dt.date().isoformat()}"


def _build_judge_prompt(a: MemoryRecord, b: MemoryRecord) -> str:
    """
    Renders the judge prompt for an already-ordered (older `a`, newer `b`)
    pair, injecting each memory's date when it has one.

    The temporal gap is what most often separates CONTRADICTION from UPDATE
    ("Berlin -> Madrid" two years apart is an UPDATE; same day is a
    CONTRADICTION), and the model can't see it unless we put it in the prompt.
    """
    return _JUDGE_PROMPT.format(
        label_a=_date_label("older", a.created_at),
        label_b=_date_label("newer", b.created_at),
        text_a=a.text,
        text_b=b.text,
    )


def _clip(text: str, limit: int = 60) -> str:
    """
    Shorten `text` for a one-line summary without cutting mid-word.

    A raw text[:limit] slice produces dangling fragments like
    "...eats up close to an hour, one directio" — the summary is the first
    thing a human reads, so trim back to the last whole word and append an
    ellipsis instead.

    - Text already within `limit` is returned unchanged, with no ellipsis.
    - Longer text is cut back to the last space that fits.
    - Text with no space to break on (e.g. a long URL) is hard-cut at `limit`
      as a last resort, so the helper never returns an empty string.
    """
    if len(text) <= limit:
        return text
    head = text[:limit].rsplit(" ", 1)[0]
    if not head:  # first word alone already exceeds limit — nothing to break on
        head = text[:limit]
    return head + "…"


def _finding_for(result: JudgeResult, a: MemoryRecord, b: MemoryRecord) -> Optional[Finding]:
    """
    Maps a judge label to a Finding, or None for UNRELATED.

    Only DUPLICATE, CONTRADICTION and UPDATE labels produce Findings.
    UNRELATED means the cheap embedding pass produced a false positive —
    no Finding, full stop. (Earlier versions of this pipeline kept the
    embedding-pass Finding around regardless of what the judge said, which
    meant a pair the judge explicitly called UNRELATED could still show up
    in the report as a duplicate. Fixed by making the judge the only
    source of Findings for candidate pairs.)
    """
    if result.label == "DUPLICATE":
        return Finding(
            type=FindingType.DUPLICATE,
            severity=Severity.LOW,
            memory_ids=[a.id, b.id],
            summary=f'Duplicate: "{_clip(a.text)}" ~ "{_clip(b.text)}"',
            detail=result.rationale,
            suggested_action="Same fact stored twice — safe to merge.",
        )
    if result.label == "CONTRADICTION":
        return Finding(
            type=FindingType.CONTRADICTION,
            severity=Severity.HIGH,
            memory_ids=[a.id, b.id],
            summary=f'Contradiction: "{_clip(a.text)}" vs "{_clip(b.text)}"',
            detail=result.rationale,
            suggested_action=(
                "These cannot both be true. Confirm which is current and "
                "delete/update the other — Mem0's ADD-only mode will not "
                "do this for you (see mem0ai/mem0#4896, #4536)."
            ),
        )
    if result.label == "UPDATE":
        return Finding(
            type=FindingType.STALE,
            severity=Severity.MEDIUM,
            memory_ids=[a.id, b.id],
            summary=f'Likely superseded: "{_clip(a.text)}" -> "{_clip(b.text)}"',
            detail=result.rationale,
            suggested_action="Consider retiring the older memory to avoid stale retrieval.",
        )
    return None


def _write_findings_atomic(findings: list[Finding], path: str) -> None:
    """
    Rewrite `path` with the full current findings list, atomically.

    We write a temp file in the same directory and os.replace() it over the
    target, so a process killed mid-write never leaves a half-written or empty
    report — the file is always either the previous complete version or the
    new complete version. This is the whole point of the incremental flush: a
    run interrupted at 60% still leaves a valid partial report on disk.
    """
    payload = [finding_to_dict(f) for f in findings]
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def find_contradictions(
    candidate_pairs: list["CandidatePair"],
    llm_call: LLMCallFn,
    on_progress: Callable[[int, int], None] | None = None,
    min_request_interval: float = 0.0,
    partial_out: str | None = None,
    on_finding: Callable[[Finding], None] | None = None,
    on_skip: Callable[["CandidatePair"], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Finding]:
    """
    Takes candidate pairs from duplicates.find_duplicate_candidates and
    classifies each with an LLM judge. Returns the list of Findings.

    Judging is sequential (one HTTP call per candidate pair) — with top-k=5 on
    even a modest memory store, this can be dozens to hundreds of calls, and
    with no feedback it looks hung rather than working. on_progress, if given,
    is called as on_progress(done, total) after each pair. cli.py wires this to
    a stderr progress line by default.

    Resilience knobs, all opt-in and off by default so existing callers/tests
    behave exactly as before:

    - min_request_interval: seconds to sleep before every call except the
      first. A soft throttle for endpoints that limit request frequency. 0.0
      means no delay at all.
    - partial_out: if set, the full findings list is re-written to this path
      (atomically) after every pair, so an interrupted run still leaves a valid
      partial report. cli.py points this at --json-out.
    - on_finding(finding): called for each emitted Finding, for callers that
      want to stream results themselves.
    - on_skip(pair): called for each pair abandoned because the judge kept
      returning HTTP 429 past its retry budget. Such a pair is skipped, not
      fatal — an audit over 90% of the data beats a traceback at 60%. The judge
      factories already retry with backoff; if the call *still* raises a rate-
      limit error here, the retries are exhausted and we move on.
    """
    findings: list[Finding] = []
    total = len(candidate_pairs)
    for done, pair in enumerate(candidate_pairs, start=1):
        if done > 1 and min_request_interval > 0:
            sleep(min_request_interval)

        a, b = pair.record_a, pair.record_b
        try:
            result = judge_pair(a, b, llm_call)
        except Exception as exc:  # noqa: BLE001
            if not _is_rate_limit_error(exc):
                raise
            # Retries (in the judge factory) are exhausted — skip this pair
            # rather than crashing the whole audit, and keep going.
            print(
                f"mem-audit: skipping pair ({a.id}, {b.id}) — judge rate-limited "
                f"past retry budget: {exc}",
                file=sys.stderr,
            )
            if on_skip:
                on_skip(pair)
            if on_progress:
                on_progress(done, total)
            if partial_out is not None:
                _write_findings_atomic(findings, partial_out)
            continue

        if on_progress:
            on_progress(done, total)

        finding = _finding_for(result, a, b)
        if finding is not None:
            findings.append(finding)
            if on_finding:
                on_finding(finding)

        if partial_out is not None:
            _write_findings_atomic(findings, partial_out)

    return findings


def _safe_parse(raw: str) -> dict:
    """LLM output is untrusted formatting-wise (not security-wise) — be defensive."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1] if "\n" in text else text
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"label": "UNRELATED", "rationale": f"unparseable judge output: {raw[:100]}"}
    if data.get("label") not in _LABELS:
        data["label"] = "UNRELATED"
    return data
