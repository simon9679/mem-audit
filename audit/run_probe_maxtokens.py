"""
Probe F vs G (max_tokens=16000 runs). F completed all 33 sessions clean; G was
transport-limited (429 on 21/33, 0 truncation on the 12 that ran). So:

  F vs G full    — both dumps as-is (G's 21 missing sessions inflate it, like the
                   A/B full number, but here the loss is transport, not truncation)
  F vs G cleaned — restricted to sessions that ran clean in BOTH (= G's 12
                   transport-clean, JSON-clean sessions; F is clean on all). This
                   is the stability number: 0 truncation, no store-contamination
                   caveat beyond the missing-session tail.
  F vs F         — positive control, must be 0.

Reads dumps + run_log from outside the repo; writes result JSONs there.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

PY = sys.executable
HERE = Path(__file__).resolve().parent
PROBE = HERE / "symdiff_probe.py"
D = Path(os.environ.get("MEM0_OUT_DIR", "./mem0_maxtokens"))  # local run dir, outside the repo


def load(label, did):
    return json.load(open(D / f"dump_{label}_{did}.json", encoding="utf-8"))["facts"]


def write_list(name, texts):
    p = D / name
    json.dump(list(texts), open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return p


def run(a, b, out):
    r = subprocess.run([PY, str(PROBE), "--a", str(a), "--b", str(b), "--json-out", str(D / out)],
                       capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode:
        sys.stdout.write(r.stderr)


def main():
    rl = json.load(open(D / "run_log.json", encoding="utf-8"))["runs"]
    F = load("F", "p8")
    G = load("G", "p8")
    n = rl["F"]["n_sessions"]
    bad_G = set(rl["G"]["transport_failed_sessions"]) | set(rl["G"]["json_failed_sessions"])
    clean = sorted(set(range(n)) - bad_G)
    print(f"F sessions clean: all {n}; G transport-clean sessions: {clean} (n={len(clean)})\n")

    f_full = write_list("probe_F_full.json", [f["text"] for f in F])
    g_full = write_list("probe_G_full.json", [f["text"] for f in G])
    f_clean = write_list("probe_F_clean.json", [f["text"] for f in F if f["session_idx"] in clean])
    g_clean = write_list("probe_G_clean.json", [f["text"] for f in G if f["session_idx"] in clean])

    print("========== F vs G  (FULL) ==========")
    run(f_full, g_full, "res_FG_full.json")
    print("\n========== F vs G  (CLEANED: sessions clean in both) ==========")
    run(f_clean, g_clean, "res_FG_clean.json")
    print("\n========== F vs F  (POSITIVE control) ==========")
    run(f_full, f_full, "res_FF.json")


if __name__ == "__main__":
    main()
