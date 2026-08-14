# RESULTS — Arena order effect, within-run balanced design

Registered in [`PREREG_arena_order_effect_balanced.md`](PREREG_arena_order_effect_balanced.md)
(commit precedes the first API call in git history). Runner:
[`run_balanced.py`](run_balanced.py). Raw judgments, provider log, manifest, and per-prompt table
under [`run_balanced/`](run_balanced/). 60/60 calls completed; exit 0; the STOP-no-retry policy did
not fire. Provider probe passed before the run; SHA self-check (5 frozen inputs) and orientation
(20/20) passed before the first call.

## Metrics (all recomputed from the 60 raw judgments)
| Metric | Definition | Result |
|---|---|---|
| **M1** | cross-order (Pass 1 vs Pass 2) outcome differs | **7/20 = 0.35** |
| **M2** | same-order (Pass 1 vs Pass 3) outcome differs | **0/20 = 0.00** |
| **M3** | exact McNemar, cross-order tie/decision, directional | **p = 0.375** (tie-under-BA 4 : tie-under-AB 1); not significant |

Same-order agreement was total — Pass 1 and Pass 3 matched on all 20 prompts at the **verdict**
level, not just the reduced outcome. The judge is effectively deterministic at fixed order here.

The 7 cross-order-differing prompts: 5 are decision↔tie (q01, q03, q10, q14, q16), 2 are strict
candidate↔baseline flips (q05 baseline→candidate, q18 candidate→baseline).

## Which prediction held
- **Prediction A** (order effect carries signal beyond judge stochasticity) required M3 **p ≤ 0.0625**
  with a directional tie-excess under BA **and** M2 ≪ M1. The M3 clause **fails** (p = 0.375):
  4:1 is the same direction as the historical 5:0 but far from significant at n = 5 discordant. **A is not met.**
- **Prediction B** (finding withdrawn) is written as "M3 p > 0.0625 **or** M2 comparable to M1."
  M3 p = 0.375 > 0.0625, so B's first clause is literally true — **but** its withdrawal reading
  assumes the cross-order instability is ordinary judge noise, and that assumption is contradicted here.

- **Registered resolution rule fires:** *M3 not significant, but M2 ≪ M1.* M2 = 0.00 is as far below
  M1 = 0.35 as the instrument allows. Per the prereg, the result is **INCONCLUSIVE** — the finding is
  **neither confirmed nor withdrawn**, and the power limitation is recorded.

## What the run actually shows
- The order effect on outcomes is **real and cleanly isolated.** With same-order stochasticity at
  exactly zero (M2 = 0/20), the entire 7/20 cross-order instability is attributable to AB↔BA
  **order**, not to judge randomness. Order changes the outcome for roughly one prompt in three.
- The **specific** point-4 mechanism — a *directional* drift toward ties under BA beyond chance —
  is **not confirmed** at this n. The fresh balanced run gives 4:1 (p = 0.375), where scoring_05's
  historical recovery gave a clean 5:0 (p = 0.0625). The one AB-side tie (q16) breaks the clean
  asymmetry; the direction is preserved (4 of 5 ties under BA) but the magnitude is not decisive.
- Because M2 ≪ M1, the instability cannot be dismissed as noise; because M3 is not significant, the
  directional claim cannot be asserted. That is exactly the case the INCONCLUSIVE rule was
  pre-registered to cover.

## Scope / relation to standard metrics (unchanged from prereg)
This is **not** an audit of Arena-Hard, which judges each query in both orders and aggregates by
Bradley–Terry; that permutation is a built-in protection. These numbers measure instability
**before** aggregation. The standard **position-inconsistency** metric is built on *decisive*
verdicts, so the 5 decision↔tie transitions that dominate M1 here **do not enter it by
construction** — the quantity measured is not captured by the standard metric.

## Limits
n = 20 prompts, single judge model, one balanced run. INCONCLUSIVE means what it says: this run
can neither confirm the directional tie-drift nor attribute the order effect to noise. A larger n
or more passes would be needed to move M3 off the discreteness floor.
