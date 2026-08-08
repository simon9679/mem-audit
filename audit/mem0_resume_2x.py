"""
Resumable ingest engine for mem0ai 2.0.17 (H2/I2 reproducibility measurement).

Separate from mem0_resume.py on purpose: that file is the record of what produced
the frozen 1.0.11 data and is not edited. 2.x differs in ways that matter here:

  * add() is a single additive-extraction LLM call (no O(store) update-decision).
  * get_all()/search() take filters={"user_id": ...} and top_k (NOT user_id/limit),
    and top_k DEFAULTS TO 20 — dumping with the default would silently cap the store
    at 20 facts. Both reads here pass top_k=100000 and assert the count != top_k.
  * a failed LLM call now raises (LLMError) instead of the old silent return [],
    so the resumable clean-stop is just the exception path; no swallow to detect.

Guards (registered in PREREG_HI_2x.md):
  - get_all truncation guard: returned count must be < top_k.
  - single-call sanity: exactly one LLM call per session; stop and report otherwise.
"""
import gc
import json
import os
import shutil
import threading
import time

os.environ.setdefault("MEM0_TELEMETRY", "False")

MAX_TOKENS = 2000
MODEL = "cerebras/gpt-oss-120b"
TOP_K = 100000  # far above the ~180 expected; guarded below

CALL_LOG = []
_lock = threading.Lock()
_pace_lock = threading.Lock()
_last = [0.0]
_installed = [False]


def install_wrapper(min_interval=15.0):
    import litellm
    if _installed[0]:
        return
    orig = litellm.completion

    def wrapped(*a, **k):
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
            CALL_LOG.append({"finish_reason": fr, "content_chars": cc, "usage_total": usage})
        return resp

    litellm.completion = wrapped
    _installed[0] = True


def cfg(cdir, coll):
    return {"vector_store": {"provider": "chroma", "config": {"collection_name": coll, "path": cdir}},
            "embedder": {"provider": "huggingface", "config": {"model": "sentence-transformers/all-MiniLM-L6-v2"}},
            "llm": {"provider": "litellm", "config": {"model": MODEL, "temperature": 0, "max_tokens": MAX_TOKENS}}}


def session_text(s):
    return "\n".join(f"{t['role']}: {t['content']}" for t in s.get("dialogue", []))


def _get_all_guarded(m, uid):
    raw = m.get_all(filters={"user_id": uid}, top_k=TOP_K)
    items = raw.get("results", raw) if isinstance(raw, dict) else raw
    if len(items) == TOP_K:
        raise RuntimeError(f"get_all returned exactly top_k={TOP_K} for {uid!r} — "
                           f"this is a silent truncation, not a full dump. Aborting.")
    return items


def load_state(path):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {"last_completed": -1, "history": []}


def save_state(path, st):
    json.dump(st, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


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
    shutil.copytree(src, dst)


def write_dump(cdir, coll, uid, label, out_dir):
    from mem0 import Memory
    m = Memory.from_config(cfg(cdir, coll))
    items = _get_all_guarded(m, uid)
    facts = [{"text": it.get("memory") or it.get("text") or "",
              "session_idx": (it.get("metadata") or {}).get("session_idx")} for it in items]
    del m; gc.collect()
    json.dump({"label": label, "dialogue_id": "p8", "user_id": uid, "facts": facts},
              open(os.path.join(out_dir, f"dump_{label}_p8.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return len(facts)


def advance_run(sessions, label, uid, coll, cdir, state_path, window, out_dir,
                min_interval=15.0, log=print):
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
    cp_before = st["last_completed"]

    m = Memory.from_config(cfg(cdir, coll))
    for i in range(start, len(sessions)):
        size_before = len(_get_all_guarded(m, uid))
        cs = len(CALL_LOG)
        try:
            m.add(session_text(sessions[i]), user_id=uid, metadata={"session_idx": i})
        except Exception as e:
            size_after = None
            try:
                size_after = len(_get_all_guarded(m, uid))
            except Exception:
                pass
            del m; gc.collect()
            if size_after is not None and size_after != size_before:
                _rmtree(cdir); _copytree(snap, cdir); _rmtree(snap)
                st["last_completed"] = cp_before
                save_state(state_path, st)
                log(f"  [{label}] s{i} PARTIAL-WRITE -> window rolled back to s{cp_before}")
                return "ROLLED_BACK", cp_before
            save_state(state_path, st)
            log(f"  [{label}] s{i} LLM error / 429 (clean boundary) -> stop; checkpoint s{st['last_completed']}: {type(e).__name__}")
            return "RATE_LIMITED", st["last_completed"]

        n_calls = len(CALL_LOG) - cs
        if n_calls != 1:
            # single-call sanity gate (PREREG): must be exactly one extraction call.
            del m; gc.collect()
            save_state(state_path, st)
            log(f"  [{label}] s{i} CALL-COUNT ANOMALY: {n_calls} LLM calls (expected 1). "
                f"Installed package does not match the single-call reading — STOP before full run.")
            return "CALL_COUNT_ANOMALY", st["last_completed"]

        st["last_completed"] = i
        st["history"].append({"session": i, "window": window, "calls": n_calls,
                              "finish_reasons": [r["finish_reason"] for r in CALL_LOG[cs:]],
                              "usage_total": sum((r["usage_total"] or 0) for r in CALL_LOG[cs:]),
                              "store_before": size_before})
        save_state(state_path, st)
        log(f"  [{label}] s{i} store={size_before} win={window} calls={n_calls} ok")

    del m; gc.collect()
    _rmtree(snap)
    n = write_dump(cdir, coll, uid, label, out_dir)
    log(f"  [{label}] COMPLETE all {len(sessions)} sessions, {n} facts")
    return "COMPLETE", st["last_completed"]
