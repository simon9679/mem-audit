# RESULTS — Mem0 retrieval-divergence test (session 5, step 3)

PREREG: `PREREG_mem0_retrieval.md` (questions frozen, sha256
`5e51de93…`, committed as `retrieval_questions.json`). `search()` verified
embed-only → **zero LLM, zero Cerebras quota** for everything below.

## Registered clean test (H↔I) — BLOCKED on budget, not run

The clean test needs two *complete* fresh runs (H, I) at max_tokens=6000. A probe
call passed, so the pair was launched — but H 429'd from session 3 (ok s0–2,
then transport). **Tonight's F at max_tokens=16000 reserved ~1.05 M tokens (the
reservation is by max_completion_tokens, not actual output) and exhausted the
day's free-tier budget**; two 6000 runs need ~792 k more, and the daily reset has
not happened. A single probe call squeaking through is necessary but not
sufficient. So the pre-registered H↔I number (dump symdiff, retrieval symdiff,
amplification) is **deferred to a real budget reset** — not confirmed, not
refuted.

## Unregistered recon: A↔B retrieval (session-2 stores) — substantive, caveated

Exploratory, run on the two session-2 stores that persist (A, B). **Caveat: A and
B are both truncation-partial and lost *different* sessions, so their 75.6 % dump
divergence is dominated by session coverage, not by clean reproducibility.** This
does not answer "how much does post-fix reproducibility divergence reach
retrieval"; it answers "does the divergence we *did* produce (truncation) reach
retrieval" — and it is informative.

20 questions, `search(limit=5, rerank=False)` on each store, pooled, `symdiff_probe`:

| threshold | retrieval symdiff | A↔B **dump** symdiff (reference) |
|---|---|---|
| exact | 82.2 | 75.6 |
| 0.60 | 73.8 | 64.0 |
| 0.72 | 76.7 | 70.9 |
| 0.82 | 82.2 | 75.6 |

Per-question exact top-5 Jaccard: mean **0.21**; **0 of 20** questions returned
an identical top-5.

**Retrieval symdiff ≥ dump symdiff at every threshold** → retrieval does **not**
smooth storage divergence; if anything top-5 nearest-neighbour selection sharpens
it. By the pre-agreed reading (rule 7): retrieval tracking the dump = the
divergence is real and product-facing, not cosmetic.

### Amplification analysis (matched vs diverging facts)

Distinguishes "valuable content differs" from "ranking amplifies marginal noise".
For each question, retrieved facts were classed matched (a counterpart in the
other store's top-5, cosine ≥ 0.72) vs diverging, then scored by cosine to the
question:

| retrieved fact class | count | mean cosine(question, fact) |
|---|---|---|
| matched | 72 | 0.470 |
| diverging | 128 | 0.415 |

**Δ = +0.055 — tiny.** Diverging facts are almost as relevant to the question as
matched ones. So the divergence is **not** low-relevance tail noise that ranking
inflates; the facts that differ between the two runs are genuinely on-topic →
**"valuable content differs."** Two runs would hand the user different but
equally-relevant facts.

### F vs partial-G preview (max_tokens runs) — inconclusive

For completeness: F (33 sessions) vs the partial G4 (sessions 0–8 only) gave
retrieval symdiff 56–86 % and per-question Jaccard 0.12. This is **coverage-
dominated** (G4 lacks 24 sessions) and says nothing about reproducibility — noted
and set aside.

## Bottom line

- For the **defect actually found (truncation)**: it **is product-facing** — two
  truncation-afflicted runs return different, equally-relevant top-5 for all 20
  questions. Retrieval does not hide it.
- The **clean "residual reproducibility after the max_tokens fix → retrieval"**
  number is still owed and needs two complete 6000 runs; blocked purely by the
  free-tier daily budget (spent by F@16000), deferrable to a reset. The harness
  and questions are frozen and committed, so that run is one command away.
