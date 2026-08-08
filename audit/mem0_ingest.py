"""
Mem0 ingest harness for the symmetric-difference re-check (session 2).

What it measures: what Mem0 extracts from a dialogue, ingested twice under
different user_ids into fresh collections. The two dumps feed symdiff_probe.py
(copied unchanged from session 1) later.

Two failure modes are attributed separately, never conflated:

  * JSON-parse failure  — the judge answered, but with malformed JSON. Mem0
    logs "Invalid JSON response" and that session yields ~0 facts. This is a
    property of the *model's behaviour* and is measured, not retried.

  * Transport failure (HTTP 429) — the model never answered; the request was
    rejected by the free-tier queue. This carries no information about Mem0 and
    is not part of the measured system. We pace requests to avoid it (a
    throttle, not a retry: it changes no model input — same messages, order,
    context, temperature — only the spacing between calls). If a 429 still
    escapes the pacing, that session is flagged transport-corrupted, in its own
    counter, and dropped from the cleaned symdiff alongside JSON failures.

Measured system, unmodified: Mem0 (chroma local + HuggingFace all-MiniLM-L6-v2
embedder) with a litellm -> Cerebras gpt-oss-120b judge at temperature 0.
litellm (not mem0's openai provider) is used only because the openai path sends
an OpenAI-only `store` field Cerebras 400s on; litellm reaches the same model
with no such field. No retries, no model swap, no prompt changes.
"""
import logging
import os
import threading
import time

os.environ.setdefault("MEM0_TELEMETRY", "False")

MEM0_LOGGER = "mem0.memory.main"
INVALID_JSON_MARK = "Invalid JSON response"

# From mem-audit's own providers.py cerebras preset. Not tuned here; raise in one
# step if it proves insufficient at store depth, and record the value used.
DEFAULT_MIN_REQUEST_INTERVAL = 12.0


# ---------------------------------------------------------------------------
# Pacing: a global throttle on litellm.completion. mem0/llms/litellm.py looks up
# `litellm.completion` at call time, so patching the module attribute paces every
# LLM call mem0 makes (extraction + update-decision) without touching arguments.
# ---------------------------------------------------------------------------
_pace_lock = threading.Lock()
_last_call_at = [0.0]
_pacing_installed = [False]


def install_pacing(min_interval: float = DEFAULT_MIN_REQUEST_INTERVAL):
    import litellm

    if _pacing_installed[0]:
        return
    original = litellm.completion

    def paced(*args, **kwargs):
        with _pace_lock:
            wait = min_interval - (time.monotonic() - _last_call_at[0])
            if wait > 0:
                time.sleep(wait)
            _last_call_at[0] = time.monotonic()
        return original(*args, **kwargs)

    litellm.completion = paced
    _pacing_installed[0] = True


class _InvalidJsonCatcher(logging.Handler):
    """Sets .hit True whenever mem0 logs an Invalid-JSON parse failure."""

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.hit = False

    def emit(self, record):
        try:
            if INVALID_JSON_MARK in record.getMessage():
                self.hit = True
        except Exception:
            pass


def make_config(db_path: str, collection: str) -> dict:
    return {
        "vector_store": {"provider": "chroma",
                         "config": {"collection_name": collection, "path": db_path}},
        "embedder": {"provider": "huggingface",
                     "config": {"model": "sentence-transformers/all-MiniLM-L6-v2"}},
        "llm": {"provider": "litellm",
                "config": {"model": "cerebras/gpt-oss-120b", "temperature": 0}},
    }


def session_text(sess: dict) -> str:
    """One string per session: every turn as 'role: content', order preserved."""
    return "\n".join(f"{t['role']}: {t['content']}" for t in sess.get("dialogue", []))


def ingest(sessions, user_id, db_path, collection,
           min_interval: float = DEFAULT_MIN_REQUEST_INTERVAL, log=print):
    """
    Ingest sessions in order, one add() per session, with pacing.

    Returns a dict with the dump (facts + session_idx) and separate JSON /
    transport failure attributions.
    """
    import litellm  # for the RateLimitError type

    install_pacing(min_interval)
    from mem0 import Memory

    m = Memory.from_config(make_config(db_path, collection))

    logger = logging.getLogger(MEM0_LOGGER)
    catcher = _InvalidJsonCatcher()
    logger.addHandler(catcher)

    json_failed = []
    transport_failed = []
    try:
        for i, sess in enumerate(sessions):
            catcher.hit = False
            try:
                m.add(session_text(sess), user_id=user_id, metadata={"session_idx": i})
            except litellm.exceptions.RateLimitError:
                transport_failed.append(i)
                log(f"  [{user_id}] session {i} TRANSPORT-429")
                continue
            except Exception as e:  # any other transport/exception — flag, don't crash the run
                transport_failed.append(i)
                log(f"  [{user_id}] session {i} TRANSPORT-ERR {type(e).__name__}")
                continue
            if catcher.hit:
                json_failed.append(i)
                log(f"  [{user_id}] session {i} JSON-FAIL")
            else:
                log(f"  [{user_id}] session {i} ok")
    finally:
        logger.removeHandler(catcher)

    raw = m.get_all(user_id=user_id, limit=100000)
    items = raw.get("results", raw) if isinstance(raw, dict) else raw
    facts = [{"text": it.get("memory") or it.get("text") or "",
              "session_idx": (it.get("metadata") or {}).get("session_idx")}
             for it in items]

    per_session = {}
    for f in facts:
        per_session[f["session_idx"]] = per_session.get(f["session_idx"], 0) + 1

    return {
        "user_id": user_id,
        "n_sessions": len(sessions),
        "n_facts": len(facts),
        "json_failed_sessions": json_failed,
        "n_json_failures": len(json_failed),
        "transport_failed_sessions": transport_failed,
        "n_transport_failures": len(transport_failed),
        "per_session_counts": {str(k): v for k, v in sorted(per_session.items(), key=lambda kv: (kv[0] is None, kv[0]))},
        "min_request_interval": min_interval,
        "model": "cerebras/gpt-oss-120b",
        "embedder": "sentence-transformers/all-MiniLM-L6-v2",
        "facts": facts,
    }
