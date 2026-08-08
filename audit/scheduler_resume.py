"""
Scheduler daemon for the resumable H/I runs (session 5).

Every 2 hours: a robust probe (3 Cerebras calls, 15 s apart, ALL must return
finish=stop). On pass, advance the active run (H until 33, then I) by one window
via mem0_resume.advance_run — it eats as many sessions as the budget allows, then
stops cleanly at a session boundary and checkpoints. On a failed probe, do
nothing and wait for the next window. When both H and I reach 33, run the
zero-quota analysis (analyze_hi.py) and exit.

Runs detached for however long the budget takes (could be a day+). All progress
to the log file.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mem0_resume as R

PY = sys.executable
EVO = os.environ.get("EVO_EMO_PATH", "evo_emo.json")  # ES-MemEval evo_emo.json (withheld dataset)
OUT = Path(os.environ.get("MEM0_RESUME_DIR", "./mem0_resume"))  # local run dir, outside the repo
OUT.mkdir(parents=True, exist_ok=True)
WINDOW_SLEEP = 1800  # 30 min — chip away / catch the daily reset promptly

sessions = next(d for d in json.load(open(EVO, encoding="utf-8")) if d["id"] == "p8")["dialog_history"]
N = len(sessions)

RUNS = {
    "H": ("p8_run_H", "col_p8_H", str(OUT / "chroma_H"), str(OUT / "state_H.json")),
    "I": ("p8_run_I", "col_p8_I", str(OUT / "chroma_I"), str(OUT / "state_I.json")),
}


def log(m):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {m}"
    print(line, flush=True)


def complete(label):
    _, _, _, sp = RUNS[label]
    return os.path.exists(sp) and R.load_state(sp)["last_completed"] >= N - 1


def robust_probe():
    # Budget OK iff the call returns (no 429). finish_reason is irrelevant — a
    # reasoning model on a tiny max_tokens returns 'length', not a failure.
    import litellm
    for k in range(3):
        try:
            litellm.completion(model=R.MODEL, messages=[{"role": "user", "content": "reply OK"}],
                               temperature=0, max_tokens=30)
        except Exception as e:
            log(f"    probe call {k+1}/3 failed: {str(e)[:80]}")
            return False
        if k < 2:
            time.sleep(15)
    return True


def main():
    log(f"scheduler start; sessions={N}; window sleep={WINDOW_SLEEP}s")
    window = 0
    while True:
        if complete("H") and complete("I"):
            log("BOTH H AND I COMPLETE -> running analysis")
            r = subprocess.run([PY, str(HERE / "analyze_hi.py")], capture_output=True, text=True)
            (OUT / "analysis_stdout.txt").write_text(r.stdout + "\n---STDERR---\n" + r.stderr, encoding="utf-8")
            (OUT / "BOTH_COMPLETE.marker").write_text("done", encoding="utf-8")
            log("ANALYSIS DONE. exiting.")
            return
        window += 1
        log(f"=== window {window}: probing (H done={complete('H')}, I done={complete('I')}) ===")
        if robust_probe():
            log(f"    probe PASS")
            label = "H" if not complete("H") else "I"
            uid, coll, cdir, sp = RUNS[label]
            status, cp = R.advance_run(sessions, label, uid, coll, cdir, sp, window, str(OUT),
                                       min_interval=15.0, log=log)
            log(f"    window {window}: {label} -> {status}, checkpoint s{cp}")
            if status in ("COMPLETE", "ALREADY_COMPLETE", "RATE_LIMITED", "ROLLED_BACK"):
                # if we just finished a run or budget still open, loop again immediately only
                # when a run COMPLETED (try the next run same window); otherwise wait.
                if status in ("COMPLETE", "ALREADY_COMPLETE") and not (complete("H") and complete("I")):
                    continue
        else:
            log(f"    probe FAIL (429/window closed), waiting {WINDOW_SLEEP}s")
        if complete("H") and complete("I"):
            continue
        time.sleep(WINDOW_SLEEP)


if __name__ == "__main__":
    main()
