"""
Run symdiff_probe.py (unchanged) on the three Mem0 dumps.

Measurements:
  A vs B  full     — the measurement (both complete p8 dumps)
  A vs B  cleaned  — restricted to sessions that parsed in BOTH p8 runs
  A vs C           — negative control (p8 vs p2, different dialogue)
  A vs A           — positive control (must be 0% at every threshold)

Reads fact-bearing dumps + run_log from OUTSIDE the repo; writes the string-list
inputs and per-measurement result JSONs there too. Only the summary table (no
verbatim facts) is transcribed into the committed RESULTS file.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

PY = sys.executable
HERE = Path(__file__).resolve().parent
PROBE = HERE / "symdiff_probe.py"
D = Path(os.environ.get("MEM0_OUT_DIR", "./mem0_symdiff_dumps"))  # local run dir, outside the repo


def load_dump(label, did):
    d = json.load(open(D / f"dump_{label}_{did}.json", encoding="utf-8"))
    return d["facts"]  # list of {text, session_idx}


def write_list(name, texts):
    p = D / name
    json.dump(list(texts), open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return p


def run_probe(a_path, b_path, out_name):
    out = D / out_name
    r = subprocess.run([PY, str(PROBE), "--a", str(a_path), "--b", str(b_path),
                        "--json-out", str(out)], capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stdout.write(r.stderr)
    return json.load(open(out, encoding="utf-8"))


def main():
    run_log = json.load(open(D / "run_log.json", encoding="utf-8"))["runs"]
    A = load_dump("A", "p8")
    B = load_dump("B", "p8")
    C = load_dump("C", "p2")

    # clean p8 sessions: parsed (no JSON fail) AND transport-clean in BOTH A and B
    bad = set(run_log["A"]["json_failed_sessions"]) | set(run_log["A"]["transport_failed_sessions"]) \
        | set(run_log["B"]["json_failed_sessions"]) | set(run_log["B"]["transport_failed_sessions"])
    clean = set(range(run_log["A"]["n_sessions"])) - bad
    print(f"clean sessions (parsed+transport-clean in BOTH p8 runs): "
          f"{sorted(clean)}  (n={len(clean)})\n")

    a_full = write_list("probe_A_full.json", [f["text"] for f in A])
    b_full = write_list("probe_B_full.json", [f["text"] for f in B])
    c_full = write_list("probe_C_full.json", [f["text"] for f in C])
    a_clean = write_list("probe_A_clean.json", [f["text"] for f in A if f["session_idx"] in clean])
    b_clean = write_list("probe_B_clean.json", [f["text"] for f in B if f["session_idx"] in clean])

    print("========== A vs B  (FULL) ==========")
    run_probe(a_full, b_full, "res_AB_full.json")
    print("\n========== A vs B  (CLEANED) ==========")
    run_probe(a_clean, b_clean, "res_AB_clean.json")
    print("\n========== A vs C  (NEGATIVE control) ==========")
    run_probe(a_full, c_full, "res_AC.json")
    print("\n========== A vs A  (POSITIVE control) ==========")
    run_probe(a_full, a_full, "res_AA.json")


if __name__ == "__main__":
    main()
