> **SUPERSEDED by PREREG_arena_order_effect_balanced.md** — the AB-only design compared a fresh run against a historical one and was replaced by a within-run balanced design at the same cost. Not executed. No API call was ever made under this registration.

# PREREG — Judge repetition stability (same-order, zai-glm-4.7)

**Status:** Preregistered. Committed before any provider call for this measurement.
No API request for this run may precede this commit in git history.

## Why this measurement exists
Point 4 found a tie-skew by order in *close* comparisons: BA produces more ties than AB.
scoring_05 AB=9/20 ties → BA=14/20 (Fisher two-sided p=0.200, underpowered at n=20);
realpair_stress_04 AB=2/5 → BA=5/5. In a clear-gap run (glm_calibration_05) there is no
skew (2/20 → 1/20, p=1.0). Order effect and the judge's run-to-run stochasticity are
currently **inseparable**: scoring_05 has one judgment per (prompt, order). This run measures
the stochastic component alone, holding order fixed.

## Orientation (verified independently of the scoring code)
AB position A = baseline, B = candidate — confirmed by hashing the actual answers in
inputs/{baseline,candidate}_answers.json and matching A_sha256/B_sha256 in raw_judges:
**20/20 A==sha(baseline), 20/20 B==sha(candidate)**. Not taken from the Codex script alone.

## Hypothesis — sharpened after point 2
The position effect was originally framed as a **reversal of preference**. Point 2 showed true
sign reversals are only **1/20**; disagreement between orders is concentrated in
**decision ↔ tie** transitions (5 of 6 inconsistent pairs). The quantity measured here is the
**stability of the judge's decisiveness**, not the stability of its preference direction.

## Design
- **Pairs:** the same 20 pairs from scoring_05 (identical USER_PROMPT, ANSWER_A, ANSWER_B),
  in **AB order only** — no permutation.
- **Judge/config (identical to scoring_05):** `zai-glm-4.7`, temperature `0`,
  max_completion_tokens `1200`, reasoning_effort `none`, same RUBRIC + schema. temperature=0
  is intentional: it measures the judge's *residual* non-determinism at its production config.
- **Repeats:** 3 per pair, same AB order → **60 judgments (20 × 3)**.
- Each judgment written raw with a manifest. Technical-error retries logged as a separate line
  (actual calls vs logical comparisons) and excluded from the sample; no hidden retries.
  Provider/quota unavailable → record a blocker and stop; a partial run is not published.

## Metrics (named in advance)
1. **pairwise_disagreement_sameorder** (primary comparator). With 3 repeats there are
   C(3,2)=3 unordered repeat-pairs per prompt → **60 same-order pairs** total. This is the
   fraction of those 60 pairs whose two repeats give a different outcome in
   {candidate, tie, baseline}. It is **directly comparable** to the point-2 swap-inconsistency
   (**6/20 = 0.30**), which is itself one *cross-order* pair per prompt. If same-order pairwise
   disagreement is well below 0.30, the extra disagreement across orders is attributable to
   **order**, not judge noise.
2. **p_unstable_sameorder** (per-prompt decision metric). Fraction of the 20 prompts where the
   3 AB-order repeats are **not all identical** in {candidate, tie, baseline}.

## Predictions — registered before the run, all four
**On the per-prompt metric (`p_unstable_sameorder`):**
- **A (primary):** `p_unstable_sameorder` < **20%**. The judge at fixed order largely reproduces
  its decision, so the observed BA tie-skew is **not explained by stochasticity alone** (order
  carries signal).
- **B (counter):** `p_unstable_sameorder` ≥ **20%**. Decision↔tie transitions are ordinary judge
  noise, order is irrelevant, and the point-4 finding is **withdrawn**.

**On the primary comparator (`pairwise_disagreement_sameorder`), registered before the run so no
convenient metric can be chosen afterward:**
- **A2 (primary comparator):** `pairwise_disagreement_sameorder` < **0.15**, i.e. materially
  below the point-2 cross-order value of 0.30.
- **B2 (counter):** `pairwise_disagreement_sameorder` ≥ **0.15**, approaching or matching the
  cross-order 0.30 — in which case the cross-order excess is **not distinguishable** from
  same-order noise and the point-4 finding is **withdrawn**.

**Resolution rule (registered in advance):** if A and A2 give opposite answers, the result is
declared **INCONCLUSIVE** — the finding is **neither confirmed nor withdrawn**, and this is
recorded as a limitation of the run. Neither metric is designated the winner after the fact.

**Threshold justification:** modern LLM-judge Repetition Stability is typically **> 0.85**
(expected instability ≈ 15%). The 20% ceiling on `p_unstable_sameorder` and the 0.15 ceiling on
`pairwise_disagreement_sameorder` are principled cutoffs against that baseline; the earlier 45%
was too lax to distinguish signal from ordinary judge noise.

## Novelty / relation to the standard metric
The standard **position-inconsistency** in the literature is defined as choosing the **same
position in both orders** — i.e., it is built on *decisive* verdicts, and **decision↔tie
transitions do not enter it**. By construction, the quantity measured here (stability of
decisiveness) is **not captured** by that standard metric.

## Frozen inputs (SHA-256)
- PAIRS (20 × {ordinal, uid, A_sha256, B_sha256}, AB):
  `dd16c3e4805e30dc7d91b7fa30d0d54ff4ca2ba495dccdbabbf09ac4aa5e51e1`
- JUDGE_CONFIG ({judge_model, temperature, max_completion_tokens, reasoning_effort}):
  `257aa0a669bf2ae1abab256170197d460f1f51ee32cfaf2f7224d308cdb31945`
- PROMPT (RUBRIC + user template + response schema + verdict enum):
  `38bbd5797f38e17c5177e5dcb947572b09a3dcef00a092396b6feeea1016c72e`

## Limits
n=20 pairs; single judge model. A null (B/B2) does not prove the order effect absent, only that
this run cannot separate it from noise at n=20. This is not an audit of Arena-Hard, which
double-runs with permutation and aggregates by Bradley–Terry; these numbers describe
instability *before* aggregation.
