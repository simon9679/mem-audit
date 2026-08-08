# RESULTS — Mem0 symdiff re-check (session 2)

Measurement of session 1's symmetric-difference method on **Mem0**. Two ingests
of the same 33-session `p8` dialogue, fresh collections, identical config, same
order. Probe `symdiff_probe.py` byte-identical to session 1. Pre-registration:
`PREREG_mem0_symdiff.md` (committed before any dump existed).

System: Mem0 1.0.11, chroma local, HuggingFace all-MiniLM-L6-v2 embedder (same
space as the probe), litellm → Cerebras `gpt-oss-120b` @ temp 0, pacing 12 s.

## Ingest (from run_log.json)

| run | id | facts | JSON-fail sessions | 429 | parsed-with-facts sessions |
|---|---|---|---|---|---|
| A | p8 | 57 | **22 / 33** | 0 | 7 |
| B | p8 | 45 | **20 / 33** | 0 | 7 |
| C | p2 | 42 | 15 / 26 | 0 | 6 |

Pacing held: **0 transport-429 across all three runs.** The surviving failure is
a JSON-parse error — but **not** the model emitting malformed JSON.

> **Mechanism correction (established in session 4).** These "JSON failures" are
> **output truncation**, `finish_reason='length'`, not garbage generation.
> Mem0's update-decision call returns the *entire accumulated memory list* every
> turn, so its output grows linearly with the store; past ~session 9 it overruns
> `max_tokens=2000` and is cut off mid-JSON — grammar-valid but incomplete, so
> `json.loads` fails. Session 4 confirmed this directly via `finish_reason`
> (constrained decoding guarantees grammar, still truncates → still fails), and
> the same mechanism explains A/B/C here. The deeper implication: Mem0 has a
> **silent memory-size ceiling** — beyond it the store stops absorbing new facts
> with no error the application sees, only a log line. Raising `max_tokens` moves
> the ceiling; it does not remove it.

JSON failure is a run-to-run lottery, not a fixed set of unparseable sessions:
A and B fail on **14 common** sessions but each also fails ~6 others the other
run parsed. Only **5 sessions parsed in BOTH** runs (sessions 0,1,5,18,22; three
of them produced facts).

## Probe tables

**A vs B — FULL dumps** (what a user actually gets)

| threshold | \|A\| | \|B\| | \|A\B\| | \|B\A\| | symdiff% | Jaccard |
|---|---|---|---|---|---|---|
| exact | 57 | 45 | 37 | 25 | 75.61 | 0.244 |
| 0.60 | 57 | 45 | 30 | 18 | 64.00 | 0.360 |
| 0.72 | 57 | 45 | 34 | 22 | 70.89 | 0.291 |
| 0.82 | 57 | 45 | 37 | 25 | 75.61 | 0.244 |

**A vs B — CLEANED** (only the 5 sessions parsed in both runs)

| threshold | \|A\| | \|B\| | \|A\B\| | \|B\A\| | symdiff% | Jaccard |
|---|---|---|---|---|---|---|
| exact | 23 | 19 | 4 | 0 | 17.39 | 0.826 |
| 0.60 | 23 | 19 | 4 | 0 | 17.39 | 0.826 |
| 0.72 | 23 | 19 | 4 | 0 | 17.39 | 0.826 |
| 0.82 | 23 | 19 | 4 | 0 | 17.39 | 0.826 |

**A vs C — negative control** (p8 vs p2, different dialogue): 98.98 % (0.60/0.72),
100 % (exact/0.82). Two unrelated dialogues share ~nothing — the divergence
ceiling is ~99 %, and MiniLM's full-sentence baseline does **not** inflate
apparent overlap between unrelated corpora.

**A vs A — positive control**: **0.00 % at every threshold.** Greedy matcher is
sound on full-sentence input.

## The decomposition (the point)

- **Full-dump instability: ~64–76 %.** What a user of this free stack observes.
- **Cleaned symdiff is 17.4 % at *every* threshold, exact included** (Jaccard
  0.83). Because exact already equals the cosine rows, **every match is
  byte-identical** and all 19 of B's facts lie wholly inside A: on the sessions
  that parsed in both runs, the two independent temp-0 ingests extracted
  **identically**. There is **no detected semantic divergence at all** — zero
  cases of "the same fact in different words." The whole cleaned gap is 4 extra
  facts in A with no B counterpart at any threshold.
- **Those 4 extras are not genuine extraction drift.** Cleaning is incomplete by
  construction: we dropped the failed sessions, but their absence already changed
  the *store state* the surviving sessions were extracted against — A and B
  reached sessions 0/1/5 with different accumulated stores (different earlier
  failures). So the 4-fact residual is a **secondary effect of the same parse
  lottery**, leaking back through store contamination, not independent semantic
  noise.
- **Conclusion: truncation-driven data loss explains everything measurable.** Not
  "⅘ data loss, ⅕ genuine drift" — data loss accounts for all of it. The full-dump
  64–76 % is each run losing a different ~2/3 of sessions to `max_tokens`
  truncation; on what survives in both, extraction is identical, and even the tiny
  residual is that same loss re-entering through store state. True extraction
  divergence on clean input is, as far as this can measure, **≈ 0** — but it
  cannot be measured cleanly here because the store is already contaminated
  (→ session 4: raise `max_tokens` so all 33 sessions complete, then measure).

This is the same three-level pattern as session 1's TBG postmortem (extraction
dominates), reproduced on an independent system — here the top layer is a
literal parser failing two-thirds of the time on a free-tier reasoning model.

## Prediction vs fact (PREREG not edited)

| quantity | predicted | actual | verdict |
|---|---|---|---|
| \|A\|, \|B\| | 80–170 | 57, 45 | **below** (parse loss suppressed volume) |
| JSON failures / run | 1–10 | 22, 20 | **far above** — the headline miss |
| 429 / run | 0–4 | 0, 0 | ✓ (pacing) |
| clean subset | 18–31 | 5 | **far below** (consequence of the miss) |
| A↔B full, exact | 95–100 | 75.61 | **below** — Mem0 facts byte-match often (~20 identical) |
| A↔B full, 0.60/0.72/0.82 | 35–58 / 50–70 / 65–83 | 64 / 70.9 / 75.6 | 0.82 ✓; 0.60,0.72 above |
| A↔B cleaned | 30–55 / 45–66 / 60–80 | 17.4 (all thr) | **below, ~2× over** — extraction identical on clean sessions |
| full − cleaned gap | 0–15 pp | ~47–58 pp | **far above** — the finding |
| negative control 0.60 | 80–95 | 98.98 | above (cleaner separation) |
| positive control | 0 | 0 | ✓ |

Honest read: I under-predicted the JSON-failure rate ~3×, and that miss cascaded
through volume and clean-subset size. The decomposition *logic* held — and the
data landed hard on the branch PREREG named "large gap → most instability is data
loss at the parse layer," a finding aimed straight at the mem-audit audience.

## TBG baseline (session 1, same probe)

| threshold | exact | 0.60 | 0.72 | 0.82 |
|---|---|---|---|---|
| TBG p8 symdiff% | 94.74 | 61.11 | 73.42 | 79.52 |
| Mem0 p8 full symdiff% | 75.61 | 64.00 | 70.89 | 75.61 |

Not directly comparable (TBG = 50 short labels each side; Mem0 = 45–57 full
sentences; different extractors), which is why exact diverges most (Mem0 facts
byte-match across runs, TBG labels almost never). The shared structure is the
method, not the numbers.

**Only the exact column is comparable across the two systems** — and a reviewer
will strike any cross-system comparison of the cosine rows. The negative control
shows why: A↔C scored ~99 % even at 0.60, i.e. on full sentences the cosine
thresholds barely move off exact, whereas TBG's short labels dropped to 61 % at
0.60. The probe's threshold behaviour is **length-dependent**, so Mem0's and
TBG's 0.60/0.72/0.82 numbers sit on different scales and must not be lined up.
Exact-vs-exact is the only honest cross-system row.

## Caveat (do not oversell)

The cleaned estimate rests on **5 clean sessions, 3 with facts (23 vs 19)** —
thin. It firmly shows the full-dump number is inflated by truncation loss, but a
*precise* semantic-stability figure for Mem0 needs a stack where the update
payload does not overrun `max_tokens` (→ session 4). The robust, reportable
result is the top layer: **output truncation of Mem0's whole-memory update call
against `max_tokens` (`finish_reason='length'`) drops facts on ~60–67 % of
sessions and is the dominant instability — a run-to-run lottery, and a silent
memory-size ceiling that is model-independent (it is a payload-vs-output-cap
limit, not a generation-quality one).**
