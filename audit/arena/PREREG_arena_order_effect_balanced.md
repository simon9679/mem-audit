# PREREG — Arena order effect, within-run balanced design (zai-glm-4.7)

**Status:** Preregistered. Committed and pushed before any provider call for this measurement.
No API request for this run may precede this commit in git history. Supersedes
`PREREG_judge_repetition_stability.md` (AB-only, not executed).

Everything below — thresholds, metrics, schedule, tie handling, execution policy, predictions,
resolution rule — is fixed before the first call. Any change means a new experiment ID and a new
run; nothing here is edited after the first call.

## Why balanced within-run
The AB-only design compared a fresh run against the *historical* scoring_05 run (different day,
same config). This design instead measures the order effect and the judge's stochasticity
**within a single run**, at the same 60-call cost, so the cross-order and same-order comparisons
are freshly generated under identical conditions.

## Orientation (verified independently of the scoring code)
AB position A = baseline, B = candidate — confirmed by hashing inputs/{baseline,candidate}_answers
and matching A_sha256/B_sha256 in scoring_05 raw_judges: **20/20 A==sha(baseline), 20/20 B==sha(candidate)**.

## Context recovery from scoring_05 (recomputed from raw judgments, not FINAL)
- outcomes-differ (cross-order candidate/tie/baseline): **6/20**
- strict sign reversal (candidate↔baseline): **1/20**
- decision↔tie transitions: **5**
- tie discordance, directional: **5 decision→tie under BA : 0 tie→decision under BA (5:0)**
- exact McNemar two-sided on 5:0: **p = 0.0625**
Each is reproducible on a fresh clone from scoring_05/raw_judges.

## Design — 60 calls, three passes over the 20 prompts
- **Pass 1:** prompts 1–10 in **AB**, prompts 11–20 in **BA**.
- **Pass 2:** the **reversed** order for each prompt (1–10 BA, 11–20 AB).
- **Pass 3:** repeats **Pass 1's** order (1–10 AB, 11–20 BA).

Each prompt yields, within this one run:
- one fresh **cross-order** pair (Pass 1 vs Pass 2), and
- one fresh **same-order** pair (Pass 1 vs Pass 3).

Outcome per judgment is reduced to the candidate frame {candidate, tie, baseline} using the
verified orientation (AB: candidate=B; BA: candidate=A).

## Metrics (fixed in advance)
- **M1** — 20 fresh swap-pairs. Fraction of prompts whose outcome differs between Pass 1 and Pass 2.
- **M2** — 20 fresh same-order pairs. Same fraction between Pass 1 and Pass 3. A separate estimate
  of the judge's stochasticity and a mechanism separator — **not** a comparison sample against M1.
- **M3 — primary confirmatory criterion.** Exact paired **McNemar** on the Pass 1 vs Pass 2 table,
  binary outcome **tie / decision**. Discordant pairs counted **directionally**: how many prompts
  went decision→tie under BA and how many under AB.
- M1 and M2 are **not** independent samples — they are the same 20 prompts.
- The 20% and 0.15 thresholds from the superseded prereg **do not carry over.**

## Power limitation (recorded before the run)
Exact McNemar is discrete; significance is set by the **directional imbalance**, not the count of
disagreements. Illustration on the historical scoring_05 discordance (5:0):
4:0 → p=0.125, 5:0 → p=0.0625, 5:1 → p=0.219, 6:0 → p=0.031, 6:1 → p=0.125, 7:1 → p=0.070,
8:1 → p=0.039. This illustrates discreteness; it is **not** a requirement to reproduce six pairs.
At n=20 the run may return an indeterminate result, and that is expected.

## Predictions — registered before the first call, both
- **A:** M3 gives **p ≤ 0.0625** with the directional excess toward ties under BA, **and** M2 is
  materially lower than M1. The order effect carries signal beyond the judge's stochasticity.
- **B:** M3 gives **p > 0.0625**, **or** M2 is comparable to M1. Decision↔tie transitions are not
  distinguishable from ordinary judge noise, and the point-4 finding is **withdrawn**.

**Resolution rule:** if M3 is not significant **but** M2 is much lower than M1, the result is
declared **INCONCLUSIVE** — the finding is neither confirmed nor withdrawn, and the power
limitation is recorded. No metric is designated the winner after the fact.

## Execution policy (fixed now, before any call)
Any technical error (non-200 HTTP, network failure, or a response that is not schema-valid with a
verdict in the allowed set) causes an immediate **STOP with no retry**. Rationale: a retry mid
balanced schedule breaks pass balance and makes the cross-order and same-order pairs
non-comparable. On failure a blocker is recorded with pass number, prompt ordinal, error code, and
the number of successful calls so far; a partial run is **not** published as a result.

## Run configuration (identical to scoring_05)
Provider Cerebras, model `zai-glm-4.7`, temperature `0`, max_completion_tokens `1200`,
reasoning_effort `none`, same RUBRIC + strict json_schema. Each judgment written raw to disk
immediately, before any counting; a manifest is written after. Provider + quota checked before the
first logical call; no access → blocker and stop.

## Frozen inputs (SHA-256)
- PAIRS (20 × {ordinal, uid, A_sha256, B_sha256}):
  `dd16c3e4805e30dc7d91b7fa30d0d54ff4ca2ba495dccdbabbf09ac4aa5e51e1`
- JUDGE_CONFIG ({judge_model, temperature, max_completion_tokens, reasoning_effort}):
  `257aa0a669bf2ae1abab256170197d460f1f51ee32cfaf2f7224d308cdb31945`
- PROMPT (RUBRIC + user template + response schema + verdict enum):
  `38bbd5797f38e17c5177e5dcb947572b09a3dcef00a092396b6feeea1016c72e`
- SCHEDULE (per-prompt pass1/pass2/pass3 orders, ordinals 1–20):
  `6cb31f9919dfec563edc394f5488b037b1ad0b52e6141bbfc584a4e19c7cdf33`
- EXECUTION_POLICY (the STOP-on-any-error text above):
  `88021e2bf091edc47072aa18dbd094b7f8bfcf7637c4c6a605af896a0dc732c7`

## Scope / relation to standard metrics
This is **not** an audit of Arena-Hard, which judges each query twice with permutation and
aggregates by Bradley–Terry; that protection is built in. These numbers measure instability
**before** aggregation. The standard **position-inconsistency** metric is built on *decisive*
verdicts (same position chosen in both orders); **decision↔tie transitions do not enter it by
construction**, so the quantity measured here is not captured by it.

## Limits
n=20 prompts; single judge model. A null (B) does not prove the order effect absent, only that this
run cannot separate it from noise at n=20.
