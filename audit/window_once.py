"""
One window of the resumable H/I run. Designed to be fired hourly by Windows Task
Scheduler — which runs under the Task Scheduler service, independent of any Claude
Code session, so the run survives the session closing and reboots. (The looping
daemon it replaces was tied to the launching session.)

Each fire: robust probe (3 calls, 15 s apart, returns on the FIRST 429 so a series
of rejections is not made worse); on pass, advance the active run (H to 33, then I)
by one window; when both are complete, run the zero-quota analysis once and drop a
marker. A lockfile prevents overlapping fires.
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
LOCK = OUT / "window.lock"
LOG = OUT / "window_once.log"

sessions = next(d for d in json.load(open(EVO, encoding="utf-8")) if d["id"] == "p8")["dialog_history"]
N = len(sessions)
RUNS = {"H": ("p8_run_H", "col_p8_H", str(OUT / "chroma_H"), str(OUT / "state_H.json")),
        "I": ("p8_run_I", "col_p8_I", str(OUT / "chroma_I"), str(OUT / "state_I.json"))}


def log(m):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {m}"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def complete(label):
    _, _, _, sp = RUNS[label]
    return os.path.exists(sp) and R.load_state(sp)["last_completed"] >= N - 1


def robust_probe():
    # Budget is OK iff the call RETURNS (no 429). finish_reason is irrelevant:
    # a reasoning model on a tiny max_tokens returns 'length', which is NOT a
    # failure — only a RateLimitError/exception is. (Earlier bug: checking
    # != 'stop' rejected a working budget.)
    import litellm
    for k in range(3):
        try:
            litellm.completion(model=R.MODEL, messages=[{"role": "user", "content": "reply OK"}],
                               temperature=0, max_tokens=30)
        except Exception:
            return False  # first 429 -> stop, do not make the series worse
        if k < 2:
            time.sleep(15)
    return True


def main():
    # lock: skip if a previous fire is still running (and fresh)
    if LOCK.exists() and (time.time() - LOCK.stat().st_mtime) < 3600:
        log("another window still running (lock present) — skip")
        return
    LOCK.write_text(str(os.getpid()), encoding="utf-8")
    try:
        if complete("H") and complete("I"):
            if not (OUT / "BOTH_COMPLETE.marker").exists():
                log("both complete -> running analysis")
                r = subprocess.run([PY, str(HERE / "analyze_hi.py")], capture_output=True, text=True)
                (OUT / "analysis_stdout.txt").write_text(r.stdout + "\n---ERR---\n" + r.stderr, encoding="utf-8")
                (OUT / "BOTH_COMPLETE.marker").write_text("done", encoding="utf-8")
                log("analysis done, marker written")
            else:
                log("both complete, marker present — nothing to do")
            return
        if not robust_probe():
            log("probe FAIL (budget/window closed) — nothing to do this hour")
            return
        label = "H" if not complete("H") else "I"
        uid, coll, cdir, sp = RUNS[label]
        win = int(time.time() // 3600)
        log(f"probe PASS -> advancing {label} (window tag {win})")
        status, cp = R.advance_run(sessions, label, uid, coll, cdir, sp, win, str(OUT),
                                   min_interval=15.0, log=log)
        log(f"{label} -> {status}, checkpoint s{cp}")
    finally:
        try:
            LOCK.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    main()
