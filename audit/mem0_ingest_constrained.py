"""
Mem0 ingest harness — Cerebras + constrained decoding (session 4).

Identical to mem0_ingest.py (session 2: chroma local, HuggingFace MiniLM embedder,
litellm -> Cerebras gpt-oss-120b @ temp 0, 12 s pacing, per-session metadata,
"Invalid JSON response" logger capture) with EXACTLY ONE change: the decoding
mode. mem0's add() pipeline asks the judge for response_format={"type":
"json_object"} on both structured calls (fact extraction, update decision); this
harness intercepts litellm.completion and upgrades that to a strict json_schema,
so Cerebras constrains generation to the exact schema and cannot emit output that
fails mem0's parse.

Same model, same temperature, same prompts, no retries — only json_object ->
json_schema+strict. So runs D/E are directly comparable to A/B: one variable.

Schemas come from mem0's own prompts/parsing:
  * extraction  -> {"facts": [str, ...]}          (main.py parses ["facts"])
  * update      -> {"memory": [{id,text,event,old_memory}]}  (parses ["memory"])
The two calls are told apart by a marker unique to the update prompt
("smart memory manager"); everything else gets the facts schema.
"""
import logging
import os
import threading
import time

os.environ.setdefault("MEM0_TELEMETRY", "False")

MEM0_LOGGER = "mem0.memory.main"
INVALID_JSON_MARK = "Invalid JSON response"
DEFAULT_MIN_REQUEST_INTERVAL = 12.0
UPDATE_MARKER = "smart memory manager"  # unique to DEFAULT_UPDATE_MEMORY_PROMPT

FACTS_SCHEMA = {
    "type": "object",
    "properties": {"facts": {"type": "array", "items": {"type": "string"}}},
    "required": ["facts"],
    "additionalProperties": False,
}

# strict mode requires every property listed in `required` and additionalProperties
# false; old_memory is only meaningful on UPDATE, so it is nullable and the model
# emits null elsewhere (mem0 reads it only for updates — a null is harmless).
MEMORY_SCHEMA = {
    "type": "object",
    "properties": {
        "memory": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "event": {"type": "string", "enum": ["ADD", "UPDATE", "DELETE", "NONE"]},
                    "old_memory": {"type": ["string", "null"]},
                },
                "required": ["id", "text", "event", "old_memory"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["memory"],
    "additionalProperties": False,
}


def _schema_for(messages) -> dict:
    blob = " ".join(m.get("content", "") for m in messages if isinstance(m, dict))
    if UPDATE_MARKER in blob:
        return {"name": "memory_update", "strict": True, "schema": MEMORY_SCHEMA}
    return {"name": "fact_extraction", "strict": True, "schema": FACTS_SCHEMA}


_patch_lock = threading.Lock()
_last_call_at = [0.0]
_installed = [False]


def install_constrained_pacing(min_interval: float = DEFAULT_MIN_REQUEST_INTERVAL):
    """Wrap litellm.completion once: upgrade json_object -> json_schema(strict),
    and pace calls. Both compose in a single wrapper."""
    import litellm

    if _installed[0]:
        return
    original = litellm.completion

    def wrapped(*args, **kwargs):
        rf = kwargs.get("response_format")
        if isinstance(rf, dict) and rf.get("type") == "json_object":
            messages = kwargs.get("messages") or (args[1] if len(args) > 1 else [])
            kwargs["response_format"] = {"type": "json_schema", "json_schema": _schema_for(messages)}
        with _patch_lock:
            wait = min_interval - (time.monotonic() - _last_call_at[0])
            if wait > 0:
                time.sleep(wait)
            _last_call_at[0] = time.monotonic()
        return original(*args, **kwargs)

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
                "config": {"model": "cerebras/gpt-oss-120b", "temperature": 0}},
    }


def session_text(sess: dict) -> str:
    return "\n".join(f"{t['role']}: {t['content']}" for t in sess.get("dialogue", []))


def ingest(sessions, user_id, db_path, collection,
           min_interval: float = DEFAULT_MIN_REQUEST_INTERVAL, log=print):
    import litellm

    install_constrained_pacing(min_interval)
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
            except Exception as e:
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
        "user_id": user_id, "n_sessions": len(sessions), "n_facts": len(facts),
        "json_failed_sessions": json_failed, "n_json_failures": len(json_failed),
        "transport_failed_sessions": transport_failed, "n_transport_failures": len(transport_failed),
        "per_session_counts": {str(k): v for k, v in sorted(per_session.items(), key=lambda kv: (kv[0] is None, kv[0]))},
        "min_request_interval": min_interval, "model": "cerebras/gpt-oss-120b",
        "decoding": "constrained (json_schema strict)",
        "embedder": "sentence-transformers/all-MiniLM-L6-v2", "facts": facts,
    }
