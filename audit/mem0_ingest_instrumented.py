"""
Mem0 ingest harness — Cerebras, plain json_object, raised max_tokens, with
per-call finish_reason instrumentation (session 4, revised).

The session-4 finding: the "JSON failures" of sessions 2/4 are output truncation
(finish_reason='length'), not malformed JSON — Mem0's update-decision call
returns the whole accumulated memory list every turn, and past ~session 9 it
overruns max_tokens. The lever is max_tokens, not the decoding mode or the model
(truncation is provider-independent: a payload-vs-output-cap limit).

So this harness changes exactly ONE thing vs session 2's A/B: **max_tokens
2000 -> 16000** (mem0's litellm path forwards config max_tokens to the request).
Decoding stays plain json_object; same model, temperature, prompts, pacing, no
retries. Runs F/G are directly comparable to A/B on that one knob.

Instrumentation: litellm.completion is wrapped (pacing, as before) and now also
records, per call: call type (extraction vs update), finish_reason, response
length in chars, prompt length in chars. The ingest loop tags each call with its
session_idx and the store size entering that session. This makes truncation a
measured quantity and yields the store-size -> output-length curve that says
where the (moved, not removed) memory ceiling now sits.
"""
import logging
import os
import threading
import time

os.environ.setdefault("MEM0_TELEMETRY", "False")

MEM0_LOGGER = "mem0.memory.main"
INVALID_JSON_MARK = "Invalid JSON response"
UPDATE_MARKER = "smart memory manager"
DEFAULT_MIN_REQUEST_INTERVAL = 12.0
MAX_TOKENS = 16000

# Per-call instrumentation, filled by the litellm.completion wrapper.
CALL_LOG = []
_call_lock = threading.Lock()
_pace_lock = threading.Lock()
_last_call_at = [0.0]
_installed = [False]


def _extract(resp):
    try:
        ch = resp.choices[0]
        fr = getattr(ch, "finish_reason", None)
        content = getattr(getattr(ch, "message", None), "content", None) or ""
        return fr, len(content)
    except Exception:
        return None, None


def install_wrapper(min_interval: float = DEFAULT_MIN_REQUEST_INTERVAL):
    import litellm

    if _installed[0]:
        return
    original = litellm.completion

    def wrapped(*args, **kwargs):
        messages = kwargs.get("messages") or (args[1] if len(args) > 1 else [])
        blob = " ".join(m.get("content", "") for m in messages if isinstance(m, dict))
        call_type = "update" if UPDATE_MARKER in blob else "facts"
        prompt_chars = len(blob)
        with _pace_lock:
            wait = min_interval - (time.monotonic() - _last_call_at[0])
            if wait > 0:
                time.sleep(wait)
            _last_call_at[0] = time.monotonic()
        resp = original(*args, **kwargs)
        fr, content_chars = _extract(resp)
        with _call_lock:
            CALL_LOG.append({"call_type": call_type, "finish_reason": fr,
                             "content_chars": content_chars, "prompt_chars": prompt_chars,
                             "session_idx": None, "store_size_before": None})
        return resp

    litellm.completion = wrapped
    _installed[0] = True


class _InvalidJsonCatcher(logging.Handler):
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
                "config": {"model": "cerebras/gpt-oss-120b", "temperature": 0,
                           "max_tokens": MAX_TOKENS}},
    }


def session_text(sess: dict) -> str:
    return "\n".join(f"{t['role']}: {t['content']}" for t in sess.get("dialogue", []))


def ingest(sessions, user_id, db_path, collection,
           min_interval: float = DEFAULT_MIN_REQUEST_INTERVAL, log=print):
    import litellm

    CALL_LOG.clear()
    install_wrapper(min_interval)
    from mem0 import Memory

    m = Memory.from_config(make_config(db_path, collection))

    def store_size():
        raw = m.get_all(user_id=user_id, limit=100000)
        items = raw.get("results", raw) if isinstance(raw, dict) else raw
        return len(items)

    logger = logging.getLogger(MEM0_LOGGER)
    catcher = _InvalidJsonCatcher()
    logger.addHandler(catcher)

    json_failed, transport_failed = [], []
    try:
        for i, sess in enumerate(sessions):
            catcher.hit = False
            size_before = store_size()
            start = len(CALL_LOG)
            try:
                m.add(session_text(sess), user_id=user_id, metadata={"session_idx": i})
            except litellm.exceptions.RateLimitError:
                transport_failed.append(i); log(f"  [{user_id}] s{i} TRANSPORT-429"); continue
            except Exception as e:
                transport_failed.append(i); log(f"  [{user_id}] s{i} TRANSPORT-ERR {type(e).__name__}"); continue
            # tag this session's calls
            trunc_here = 0
            for rec in CALL_LOG[start:]:
                rec["session_idx"] = i
                rec["store_size_before"] = size_before
                if rec["finish_reason"] == "length":
                    trunc_here += 1
            if catcher.hit:
                json_failed.append(i)
            tag = "JSON-FAIL" if catcher.hit else ("ok" if trunc_here == 0 else f"ok(trunc={trunc_here})")
            log(f"  [{user_id}] s{i} store={size_before} {tag}")
    finally:
        logger.removeHandler(catcher)

    raw = m.get_all(user_id=user_id, limit=100000)
    items = raw.get("results", raw) if isinstance(raw, dict) else raw
    facts = [{"text": it.get("memory") or it.get("text") or "",
              "session_idx": (it.get("metadata") or {}).get("session_idx")} for it in items]
    per_session = {}
    for f in facts:
        per_session[f["session_idx"]] = per_session.get(f["session_idx"], 0) + 1
    n_trunc = sum(1 for r in CALL_LOG if r["finish_reason"] == "length")

    return {
        "user_id": user_id, "n_sessions": len(sessions), "n_facts": len(facts),
        "json_failed_sessions": json_failed, "n_json_failures": len(json_failed),
        "transport_failed_sessions": transport_failed, "n_transport_failures": len(transport_failed),
        "n_truncations": n_trunc,
        "per_session_counts": {str(k): v for k, v in sorted(per_session.items(), key=lambda kv: (kv[0] is None, kv[0]))},
        "call_log": list(CALL_LOG),
        "min_request_interval": min_interval, "model": "cerebras/gpt-oss-120b",
        "max_tokens": MAX_TOKENS, "decoding": "plain json_object",
        "embedder": "sentence-transformers/all-MiniLM-L6-v2", "facts": facts,
    }
