"""
Driver: two plain-json_object Mem0 ingests of p8 at max_tokens=16000 (runs F, G).

F vs G is the clean stability measurement (truncation removed). Per-call
instrumentation (finish_reason, content/prompt chars, store size) is saved in
run_log for the store->output ceiling curve. Dumps + run_log OUTSIDE the repo.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mem0_ingest_instrumented import ingest, DEFAULT_MIN_REQUEST_INTERVAL, MAX_TOKENS

EVO_EMO = os.environ.get("EVO_EMO_PATH", "evo_emo.json")  # ES-MemEval evo_emo.json (withheld dataset)
OUT = Path(os.environ.get("MEM0_OUT_DIR", "./mem0_maxtokens"))  # local run dir, outside the repo
OUT.mkdir(parents=True, exist_ok=True)

RUNS = [
    ("F", "p8", "p8_run_F", "col_p8_F", OUT / "chroma_F"),
    ("G", "p8", "p8_run_G", "col_p8_G", OUT / "chroma_G"),
]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    if not os.environ.get("CEREBRAS_API_KEY", "").strip():
        sys.exit("STOP: CEREBRAS_API_KEY not set")
    data = json.load(open(EVO_EMO, encoding="utf-8"))
    by_id = {d["id"]: d for d in data}

    run_log = {
        "min_request_interval": DEFAULT_MIN_REQUEST_INTERVAL,
        "model": "cerebras/gpt-oss-120b", "max_tokens": MAX_TOKENS,
        "decoding": "plain json_object",
        "embedder": "sentence-transformers/all-MiniLM-L6-v2",
        "vector_store": "chroma (local)", "dataset": "evo_emo.json (ES-MemEval) p8",
        "runs": {},
    }

    for label, did, user_id, collection, path in RUNS:
        sessions = by_id[did]["dialog_history"]
        log(f"=== RUN {label}: id={did} user_id={user_id} sessions={len(sessions)} max_tokens={MAX_TOKENS} ===")
        t0 = time.time()
        res = ingest(sessions, user_id, str(path), collection,
                     min_interval=DEFAULT_MIN_REQUEST_INTERVAL, log=log)
        res["dialogue_id"] = did
        res["label"] = label
        res["elapsed_sec"] = round(time.time() - t0, 1)

        with open(OUT / f"dump_{label}_{did}.json", "w", encoding="utf-8") as f:
            json.dump({"label": label, "dialogue_id": did, "user_id": user_id,
                       "facts": res["facts"]}, f, ensure_ascii=False, indent=1)
        # run_log keeps everything except the fact texts (call_log has no verbatim facts)
        run_log["runs"][label] = {k: v for k, v in res.items() if k != "facts"}
        with open(OUT / "run_log.json", "w", encoding="utf-8") as f:
            json.dump(run_log, f, ensure_ascii=False, indent=2)

        log(f"RUN {label} done: n_facts={res['n_facts']} json_fail={res['n_json_failures']} "
            f"truncations={res['n_truncations']} transport={res['n_transport_failures']} "
            f"elapsed={res['elapsed_sec']}s")

    log("ALL RUNS COMPLETE.")


if __name__ == "__main__":
    main()
