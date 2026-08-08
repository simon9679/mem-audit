"""
Resumable, checkpointed Mem0 ingest engine (session 5, revised).

Motivation: the Cerebras free-tier budget only lets ~a handful of sessions
through per window. A one-shot run cannot finish 33 sessions. This engine
processes as many sessions as the current window allows, checkpoints the last
*successfully completed* session, and a scheduler resumes from the next one in a
later window — so the run completes over however many windows the budget grants,
with no guessing when the daily reset lands.

Invariants (the "no partial session" requirement):
  * Checkpoint = index of the last session whose add() fully succeeded.
  * mem0 writes to the vector store only AFTER both LLM calls (extraction +
    update-decision); a 429 raises at the LLM call, before any write — so a failed
    session leaves the store untouched. We verify this per failure (store size
    unchanged) and, as a belt-and-suspenders, snapshot the chroma dir at window
    start and restore it if a partial write is ever detected. Either way the store
    is exactly the state a continuous run would have had at that checkpoint.

Equivalence to a continuous run: the ONLY difference is that hours pass between
some sessions instead of seconds. Mem0 keeps all state in Chroma and its
update-decision prompt contains no wall-clock time, so inter-session latency
cannot change the result. (Stated in RESULTS, not hidden.)

Instrumentation per call: finish_reason, actual usage tokens, content chars,
call type, and the window index — persisted into the state file.
"""
import gc
import json
import logging
import os
import shutil
import threading
import time

os.environ.setdefault("MEM0_TELEMETRY", "False")

MAX_TOKENS = 6000
MODEL = "cerebras/gpt-oss-120b"
UPDATE_MARKER = "smart memory manager"

CALL_LOG = []
_lock = threading.Lock()
_pace_lock = threading.Lock()
_last = [0.0]
_installed = [False]

MEM0_LOGGER = "mem0.memory.main"
# mem0 SWALLOWS a failed update-decision call: on a 429 (or bad JSON) in the
# second LLM call it logs one of these and continues with empty actions, so add()
# returns "successfully" but the session's ADD/UPDATE/DELETE reconciliation never
# ran — a partial session that a continuous run would not have. We detect it here.
_DEGRADE_MARKS = ("Error in new memory actions response", "Invalid JSON response")


class _DegradeCatcher(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.hit = None

    def emit(self, record):
        try:
            msg = record.getMessage()
            for mk in _DEGRADE_MARKS:
                if mk in msg:
                    self.hit = mk
        except Exception:
            pass


def install_wrapper(min_interval=15.0):
    import litellm
    if _installed[0]:
        return
    orig = litellm.completion

    def wrapped(*a, **k):
        msgs = k.get("messages") or (a[1] if len(a) > 1 else [])
        blob = " ".join(m.get("content", "") for m in msgs if isinstance(m, dict))
        ctype = "update" if UPDATE_MARKER in blob else "facts"
        with _pace_lock:
            w = min_interval - (time.monotonic() - _last[0])
            if w > 0:
                time.sleep(w)
            _last[0] = time.monotonic()
        resp = orig(*a, **k)
        fr = cc = usage = None
        try:
            ch = resp.choices[0]
            fr = getattr(ch, "finish_reason", None)
            cc = len(getattr(getattr(ch, "message", None), "content", None) or "")
            u = getattr(resp, "usage", None)
            usage = getattr(u, "total_tokens", None) if u else None
        except Exception:
            pass
        with _lock:
            CALL_LOG.append({"call_type": ctype, "finish_reason": fr,
                             "content_chars": cc, "usage_total": usage})
        return resp

    litellm.completion = wrapped
    _installed[0] = True


def cfg(cdir, coll):
    return {"vector_store": {"provider": "chroma", "config": {"collection_name": coll, "path": cdir}},
            "embedder": {"provider": "huggingface", "config": {"model": "sentence-transformers/all-MiniLM-L6-v2"}},
            "llm": {"provider": "litellm", "config": {"model": MODEL, "temperature": 0, "max_tokens": MAX_TOKENS}}}


def session_text(s):
    return "\n".join(f"{t['role']}: {t['content']}" for t in s.get("dialogue", []))


def _store_size(m, uid):
    raw = m.get_all(user_id=uid, limit=100000)
    items = raw.get("results", raw) if isinstance(raw, dict) else raw
    return len(items)


def _rmtree(p):
    for _ in range(5):
        try:
            shutil.rmtree(p); return
        except FileNotFoundError:
            return
        except Exception:
            time.sleep(0.5)
    shutil.rmtree(p, ignore_errors=True)


def _copytree(src, dst):
    for _ in range(5):
        try:
            shutil.copytree(src, dst); return
        except Exception:
            time.sleep(0.5)
    shutil.copytree(src, dst)  # last try, raise if it fails


def load_state(path):
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    return {"last_completed": -1, "history": []}


def save_state(path, st):
    json.dump(st, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def write_dump(cdir, coll, uid, label, out_dir):
    from mem0 import Memory
    m = Memory.from_config(cfg(cdir, coll))
    raw = m.get_all(user_id=uid, limit=100000)
    items = raw.get("results", raw) if isinstance(raw, dict) else raw
    facts = [{"text": it.get("memory") or it.get("text") or "",
              "session_idx": (it.get("metadata") or {}).get("session_idx")} for it in items]
    del m; gc.collect()
    json.dump({"label": label, "dialogue_id": "p8", "user_id": uid, "facts": facts},
              open(os.path.join(out_dir, f"dump_{label}_p8.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return len(facts)


def advance_run(sessions, label, uid, coll, cdir, state_path, window, out_dir,
                min_interval=15.0, log=print):
    """Process one window: from checkpoint+1 until a 429 or all sessions done.
    Returns (status, last_completed)."""
    install_wrapper(min_interval)
    from mem0 import Memory

    st = load_state(state_path)
    start = st["last_completed"] + 1
    if start >= len(sessions):
        return "ALREADY_COMPLETE", st["last_completed"]

    snap = cdir + ".winsnap"
    _rmtree(snap)
    if os.path.exists(cdir):
        _copytree(cdir, snap)
    cp_before_window = st["last_completed"]

    logger = logging.getLogger(MEM0_LOGGER)
    catcher = _DegradeCatcher()
    logger.addHandler(catcher)

    m = Memory.from_config(cfg(cdir, coll))
    try:
        for i in range(start, len(sessions)):
            size_before = _store_size(m, uid)
            cs = len(CALL_LOG)
            catcher.hit = None
            try:
                m.add(session_text(sessions[i]), user_id=uid, metadata={"session_idx": i})
            except Exception:
                # extraction (1st) call raised — mem0 does not swallow this one.
                size_after = None
                try:
                    size_after = _store_size(m, uid)
                except Exception:
                    pass
                del m; gc.collect()
                if size_after is not None and size_after != size_before:
                    _rmtree(cdir); _copytree(snap, cdir); _rmtree(snap)
                    st["last_completed"] = cp_before_window
                    save_state(state_path, st)
                    log(f"  [{label}] s{i} PARTIAL-WRITE -> window rolled back to s{cp_before_window}")
                    return "ROLLED_BACK", cp_before_window
                save_state(state_path, st)
                log(f"  [{label}] s{i} 429 on extraction (clean boundary) -> stop; checkpoint s{st['last_completed']}")
                return "RATE_LIMITED", st["last_completed"]

            # add() returned — but mem0 SWALLOWS a failed update-decision call.
            if catcher.hit:
                # degraded session (update 429'd / bad JSON): its reconciliation
                # never ran. Do NOT checkpoint it. Store should be unchanged (no
                # write on empty actions); verify and restore if not.
                size_after = _store_size(m, uid)
                del m; gc.collect()
                if size_after != size_before:
                    _rmtree(cdir); _copytree(snap, cdir); _rmtree(snap)
                save_state(state_path, st)
                reason = "TRUNCATION" if "Invalid JSON" in catcher.hit else "UPDATE-429"
                log(f"  [{label}] s{i} DEGRADED ({reason}) -> clean stop, checkpoint s{st['last_completed']}")
                return "RATE_LIMITED", st["last_completed"]

            recs = CALL_LOG[cs:]
            trunc = sum(1 for r in recs if r["finish_reason"] == "length")
            st["last_completed"] = i
            st["history"].append({
                "session": i, "window": window, "calls": len(recs),
                "finish_reasons": [r["finish_reason"] for r in recs],
                "usage_total": sum((r["usage_total"] or 0) for r in recs),
                "content_chars": [r["content_chars"] for r in recs],
                "store_before": size_before, "truncations": trunc,
            })
            save_state(state_path, st)
            log(f"  [{label}] s{i} store={size_before} win={window} calls={len(recs)} ok")
    finally:
        logger.removeHandler(catcher)

    del m; gc.collect()
    _rmtree(snap)
    n = write_dump(cdir, coll, uid, label, out_dir)
    log(f"  [{label}] COMPLETE all {len(sessions)} sessions, {n} facts")
    return "COMPLETE", st["last_completed"]
