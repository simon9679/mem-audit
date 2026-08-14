# `audit/arena/` — answer-position order effect on a pairwise LLM judge

This bundle is **not** an audit of Arena-Hard. Arena-Hard judges every query in both
orders and aggregates by Bradley–Terry, which cancels answer position by construction.
What is measured here is the instability that exists **before** that aggregation, on a
single judge model, using an Arena-Hard-derived frozen 20-prompt subset.

The work ran as four stages, each of which constrained the next.

## 1. Calibration — does the judge work at all?

`arena_hard_glm_calibration_05` (bundle in the run archive, not in this repository).
Twenty oracle-vs-canary pairs where the correct answer is known in advance, each judged
in both orders.

From `results/CALIBRATION_05_FINAL.json`:

- oracle wins **37**, canary wins **0**, ties **3** (40 judgments, status `PASS`)
- oracle score **0.9625**; the complementary canary score, `(0 + 0.5·3)/40 = 0.0375`, is
  derived rather than a field in the file
- by position: oracle in A **0.950** (18/0/2), oracle in B **0.975** (19/0/1)

Every figure recomputes from the counts, and the position split sums back to the totals.
The technical block is clean: 40 logical calls, 40 actual attempts, 0 retries, 0 rate limits.

**Score difference between the two positions here: 0.025** (0.975 with the oracle in B
against 0.950 with it in A). The same judge on close pairs in stage 2 shows **0.125** —
five times larger in absolute magnitude.

The two differences point in **opposite directions**: the oracle scores higher in
position B, the candidate scores higher in position A. So this is not one constant
positional preference that grows stronger. It is a descriptive contrast between two
different sets of comparisons, showing that outcomes are more sensitive to permutation on
close pairs — not a measured interaction between pair difficulty and order, which would
need a test that has not been run.

## 2. Scoring — instability appears on close answers

`arena_hard_gptoss_scoring_05` (bundle in the run archive, not in this repository).
The same 20 prompts, candidate `gpt-oss-120b` against the official baseline, each prompt
judged in both orders — 40 judgments.

- candidate score **0.4875** (8 wins, 9 losses, 23 ties) — indistinguishable from baseline
- outcome differs between the two orders on **6/20** prompts
- the bundle's own summary records `position_effect = 0.125` and a position split of
  0.55 with candidate in A against 0.425 with candidate in B

The headline model score is the least interesting number here. What matters is that the
same judge that was near-symmetric on obvious pairs disagrees with itself on close ones.

## 3. Recount from raw — the disagreement is not what it looked like

Recomputed from the raw judgments rather than from the summary, with the AB orientation
verified independently by hashing the answer files (`A_sha256`/`B_sha256` matched
`inputs/{baseline,candidate}_answers.json`, 20/20 both ways).

Of the six inconsistent prompts, **five are decision↔tie transitions and only one is a
true candidate↔baseline reversal.** That changes the character of the finding: the order
does not usually flip *who wins*, it flips *whether the judge commits to a winner*.

This also disqualified a comparison that was nearly made: the literature reports 20–30%
position inconsistency, but that metric is defined as choosing the same position in both
orders — it is built on decisive verdicts, and decision↔tie transitions do not enter it
by construction. Comparing 6/20 against that number would have compared unlike
quantities. The comparable figure is the strict reversal rate, **1/20**.

## 4. Balanced within-run measurement — separating order from noise

[`PREREG_arena_order_effect_balanced.md`](PREREG_arena_order_effect_balanced.md) ·
[`RESULTS_arena_order_effect_balanced.md`](RESULTS_arena_order_effect_balanced.md) ·
[`run_balanced.py`](run_balanced.py) · [`run_balanced/`](run_balanced/)

The stage-3 result left order and the judge's own run-to-run noise inseparable: one
judgment per (prompt, order). A first design measured 60 same-order repeats and compared
them against the *historical* scoring run — that design was registered, then superseded
before execution, because a within-run design costs the same and avoids comparing across
days. The superseded registration is kept on branch
`audit/arena-judge-repetition-stability` rather than rewritten.

Three passes over the 20 prompts, 60 calls, order balanced 10/10:

| | |
|---|---|
| **M1** cross-order instability (Pass 1 vs Pass 2) | **7/20 = 0.35** |
| **M2** same-order instability (Pass 1 vs Pass 3) | **0/20 = 0.00** |
| **M3** exact McNemar, tie/decision discordance | **p = 0.375** (4:1) |

**M2 = 0 is the substantive result.** The judge reproduced itself on all twenty prompts at
fixed order, down to the verdict string. 7/20 cross-order disagreements against 0/20
same-order disagreements is strong evidence that answer position contributes to the
instability: ordinary same-order judge noise, as measured in this run, does not explain the
pattern.

Zero observed is not zero probability. At n = 20, an observed 0/20 is compatible with a
true same-order disagreement rate of up to about 16% (95% Wilson upper bound 0.161; the
rule of three gives 3/20 = 0.15). So the correct statement is that same-order noise was
not detected at this sample size, not that it is absent — and consequently not that the
whole 7/20 is attributable to order.

**M3 did not confirm the narrower hypothesis.** The stage-3 data showed tie discordance
5:0 in favour of ties under BA; the fresh run gave 4:1, and one prompt breaking the
asymmetry is enough to move exact McNemar from 0.0625 to 0.375. Direction is unchanged,
magnitude is not decisive at n = 20.

**Verdict: INCONCLUSIVE**, by the resolution rule fixed before the run — M3 not
significant but M2 ≪ M1, so the finding is neither confirmed nor withdrawn. The power
limitation was recorded in the pre-registration before any call, not discovered after.

## What this line did and did not establish

Established: on close pairs this judge changes its outcome on one prompt in three when the
answer positions are swapped, while no same-order disagreement was detected at all
(M2 = 0/20, upper bound ~16% at this n). Three observations agree in pointing that way — near-perfect discrimination on obvious pairs
(37/40, score 0.9625), a five-times larger position-associated score gap on close pairs
(0.125 against 0.025, opposite signs), and 7/20 cross-order against 0/20 same-order
disagreement in the balanced run.

Not established: that the instability runs specifically toward ties under one order, that
any constant preference for position A or B exists, or that pair difficulty and order
interact in a formally tested sense.
Also not established, and not attempted: anything about Arena-Hard's published scores,
which aggregate over both orders.

Registration precedes measurement in git history: prereg `6bcd64a` pushed 12:48, runner
`239f97d` 12:51, results `ffdc848` 13:06 — all on 2026-08-14.

## Limits

n = 20 prompts, one judge model, one provider, one frozen subset. `M2 = 0` is measured at
`temperature=0` and says nothing about the judge's behaviour at other settings. The
calibration and scoring bundles referenced in stages 1–3 live in the run archive outside
this repository; only the stage-4 measurement is published here in full.
