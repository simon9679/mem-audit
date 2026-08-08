"""
Drive the H2/I2 reproducibility pair on mem0ai 2.0.17. Two clean complete ingests of
p8 (single-call additive extraction, max_tokens=2000, temp 0). Resumable: if a budget
429 lands mid-run, the checkpoint is saved and the run can be resumed (re-invoke).
Stops loudly on the single-call-count anomaly (PREREG guard).

Paths from env (EVO_EMO_PATH, MEM0_2X_OUT) so no machine-specific data is committed.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mem0_resume_2x as R

EVO = os.environ.get("EVO_EMO_PATH", "evo_emo.json")
OUT = Path(os.environ.get("MEM0_2X_OUT", "./mem0_2x"))
OUT.mkdir(parents=True, exist_ok=True)
sessions = next(d for d in json.load(open(EVO, encoding="utf-8")) if d["id"] == "p8")["dialog_history"]
N = len(sessions)
RUNS = [("H2", "p8_run_H2", "col_p8_H2", "chroma_H2", "state_H2.json"),
        ("I2", "p8_run_I2", "col_p8_I2", "chroma_I2", "state_I2.json")]


def log(m):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {m}", flush=True)


def complete(sp):
    return os.path.exists(sp) and R.load_state(sp)["last_completed"] >= N - 1


def main():
    win = int(time.time() // 3600)
    for label, uid, coll, cdir, sfile in RUNS:
        sp = str(OUT / sfile)
        while not complete(sp):
            log(f"=== advancing {label} (checkpoint s{R.load_state(sp)['last_completed']}) ===")
            status, cp = R.advance_run(sessions, label, uid, coll, str(OUT / cdir), sp, win, str(OUT),
                                       min_interval=15.0, log=log)
            log(f"{label} -> {status} @ s{cp}")
            if status == "CALL_COUNT_ANOMALY":
                log("STOP: single-call assumption violated — do not proceed."); return
            if status in ("RATE_LIMITED", "ROLLED_BACK"):
                log(f"{label} hit a budget/rollback boundary at s{cp}; checkpoints saved, resume later.")
                return
    log("PAIR2X COMPLETE.")


if __name__ == "__main__":
    main()
