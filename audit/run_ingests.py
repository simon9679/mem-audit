"""
Driver: three Mem0 ingests for the symdiff re-check.

  A = p8 (33 sessions), run 1
  B = p8 (33 sessions), run 2  -> A vs B is the measurement
  C = p2 (26 sessions), one run -> A vs C is the negative control (different
      dialogue, same dataset/format/domain-genre)

Fact-bearing dumps and run_log.json are written OUTSIDE the git repo (ES-MemEval
is withheld text; its derivatives must not be committed). Each dump is flushed
immediately after its run, so a crash in a later run never loses an earlier one.

Runs for hours on the free tier (pacing). Launch detached, outside the Claude
session; the next session starts from the three ready dumps.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mem0_ingest import ingest, DEFAULT_MIN_REQUEST_INTERVAL

EVO_EMO = os.environ.get("EVO_EMO_PATH", "evo_emo.json")  # ES-MemEval evo_emo.json (withheld dataset)
OUT = Path(os.environ.get("MEM0_OUT_DIR", "./mem0_symdiff_dumps"))  # local run dir, outside the repo
OUT.mkdir(parents=True, exist_ok=True)

RUNS = [
    # label, dialogue id, user_id, chroma collection, chroma path
    ("A", "p8", "p8_run_A", "col_p8_A", OUT / "chroma_A"),
    ("B", "p8", "p8_run_B", "col_p8_B", OUT / "chroma_B"),
    ("C", "p2", "p2_run_C", "col_p2_C", OUT / "chroma_C"),
]


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)


def main():
    if not os.environ.get("CEREBRAS_API_KEY", "").strip():
        sys.exit("STOP: CEREBRAS_API_KEY not set in environment")

    data = json.load(open(EVO_EMO, encoding="utf-8"))
    by_id = {d["id"]: d for d in data}

    run_log = {
        "min_request_interval": DEFAULT_MIN_REQUEST_INTERVAL,
        "model": "cerebras/gpt-oss-120b",
        "embedder": "sentence-transformers/all-MiniLM-L6-v2",
        "vector_store": "chroma (local)",
        "dataset": "evo_emo.json (ES-MemEval)",
        "runs": {},
    }

    for label, did, user_id, collection, path in RUNS:
        sessions = by_id[did]["dialog_history"]
        log(f"=== RUN {label}: id={did} user_id={user_id} sessions={len(sessions)} ===")
        t0 = time.time()
        res = ingest(sessions, user_id, str(path), collection,
                     min_interval=DEFAULT_MIN_REQUEST_INTERVAL, log=log)
        res["dialogue_id"] = did
        res["label"] = label
        res["elapsed_sec"] = round(time.time() - t0, 1)

        # fact-bearing dump -> outside repo
        dump_path = OUT / f"dump_{label}_{did}.json"
        with open(dump_path, "w", encoding="utf-8") as f:
            json.dump({"label": label, "dialogue_id": did, "user_id": user_id,
                       "facts": res["facts"]}, f, ensure_ascii=False, indent=1)

        # log summary (no verbatim facts) -> run_log
        summary = {k: v for k, v in res.items() if k != "facts"}
        run_log["runs"][label] = summary
        with open(OUT / "run_log.json", "w", encoding="utf-8") as f:
            json.dump(run_log, f, ensure_ascii=False, indent=2)

        log(f"RUN {label} done: n_facts={res['n_facts']} "
            f"json_fail={res['n_json_failures']}{res['json_failed_sessions']} "
            f"transport_fail={res['n_transport_failures']}{res['transport_failed_sessions']} "
            f"elapsed={res['elapsed_sec']}s -> {dump_path.name}")

    log("ALL RUNS COMPLETE.")


if __name__ == "__main__":
    main()
