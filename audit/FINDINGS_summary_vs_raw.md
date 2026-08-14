# FINDING — automated summaries disagreeing with their own raw artifacts

Across this project, independent recomputation from primary artifacts surfaced **five
separate cases where an automated summary disagreed with the raw data it was derived
from.** In two the formal status of a run changed. In one the meaning of a reported
metric changed. In two the technical accounting was wrong while the science was not.

This is a finding about the measurement pipeline used here, not about Mem0 or
Arena-Hard. It is the concrete reason for the rule that raw evidence is written and
hashed before any interpretation, and that headline numbers are recomputed from raw
rather than read from a summary.

**The denominator, measured.** All ten surviving `arena_hard_*` bundles were later
recounted from their raw files against their own final JSON. **Every one of the ten
matched on its scientific counters** — including `calibration_05` and `scoring_05`, where
answer position was re-derived independently by hashing the answer files, 40/40 in both.
The `scoring_05` recount reproduced 8/9/23 and 6/20 exactly; the balanced order-effect run
reproduced M1, M2 and the discordance from its own 60 raw judgments; all published
manifests verify.

So the disagreements are not in the measured values. They are in **technical accounting,
integrity metadata, and classifier logic** — the parts of a summary that no one recomputes
because they look like bookkeeping rather than results. That is the more precise version
of the claim, and a narrower one.

## The five cases

### 1. `calibration_04` — a stop-gate that recorded PASS when it should have failed

A calibration run on oracle-versus-canary pairs, gating whether the scoring run could
proceed. Pre-registered threshold: `ties ≤ 1`.

The automated summary recorded **PASS**. A direct recount of the raw verdicts gave oracle
wins 18/20, canary wins 0/20, **ties 2/20** — a **FAIL** against the registered threshold.

Cause: the classifier used `v.startswith('A')`, which returns true for the tie string
`"A=B"`. The mapping was asymmetric — a tie was scored as an oracle win when the oracle
occupied position A, and left as a tie when it occupied position B:

```python
ow = (d == 'ORACLE_A' and v.startswith('A')) or (d == 'ORACLE_B' and v.startswith('B'))
# v = "A=B", d = "ORACLE_A"  ->  ow = True   (tie counted as a win)
# v = "A=B", d = "ORACLE_B"  ->  ow = False  (tie counted as a tie)
```

The consequence was not only a wrong count: because the leak ran in one direction only,
the defect would manufacture an artificial position effect. The scoring run that would
have followed was correctly never created.

**Verifiability: partial — the defect is checkable, the run is not.** The faulty classifier
survives as `codex/src/scoring04.py` line 85, byte-identical in both the live tree and the
backup (SHA-256 `25e19c7519713dda8aed57d8173707db19377259ad274cf6e29899138e8d713b`), and
the asymmetric leak reproduces from the line alone. The arithmetic also reconstructs: with
one tie leaking into a win under `ORACLE_A`, the counts become 19 wins and 1 tie, which
formally satisfies `ties ≤ 1` — the mechanism by which a FAIL was recorded as PASS.
`scoring03.py` line 112 carries the same error on the baseline side.

What cannot be shown is the run itself. The bundle `arena_hard_glm_calibration_04` was deleted during a
cleanup of five early invalid bundles, together with `arena_hard_infrastructure_probe_01`,
`arena_hard_gptoss_01`, `arena_hard_gptoss_probe_02` and `arena_hard_scoring_killtest_03`.
The raw verdicts and the faulty code no longer exist anywhere; what survives is the
session transcript in which the recount was performed. **This case is therefore recorded
as a documented loss, not offered as a checkable result.** It is included because the
loss itself is evidence: the best defect found in this project is the one that cannot be
shown to anyone.

The scoring runner actually used for `scoring_05` was checked for the same defect and is
clean — it maps verdicts through an explicit lookup table, `A=B` resolves to `TIE`
symmetrically, and its SHA-256 matches the `runner_sha256` recorded in that run's freeze
manifest. The stage-3 numbers are not an inheritance of this bug.

### 2. `gptoss_probe_02` — a valid judgment rejected by an over-strict parser

The format probe reported `JUDGE_FORMAT_PROBE_FAIL` and halted the preflight. The raw
provider response had `finish_reason: stop` and a final line reading
`**Verdict:** [[A>B]]` — a valid label.

The parser required the final line to *equal* a valid label exactly, rather than to
*contain* one, which was stricter than the specification it implemented. A run was
stopped on a parser artifact rather than on a provider or model failure.

**Verifiability: none.** `arena_hard_gptoss_probe_02` was among the five bundles deleted in
the same cleanup as case 1. The raw provider response carrying the valid label, and the
parser that rejected it, no longer exist. Like case 1, this is recorded as a documented
loss rather than offered as a checkable result — and unlike case 1, no surviving code
carries the defect.

A note on how this entry was nearly misattributed. The surviving bundle
`arena_hard_gptoss_02` also halted on a rejected judge output, with `BLOCKER.json`,
`JUDGE_ATTEMPTS_EXHAUSTED` and `INVALID_RUN_TECHNICAL`, and a draft of this document
reassigned the case to it. Checking the raw files showed the two are not the same event:
in `gptoss_02` the judge returned prose with no final label at all — no `[[`, no
`Verdict` — so rejecting it was correct, not over-strict. That bundle is an example of the
pipeline stopping properly, and it does not belong in this list.

### 3. `compare_dumps.py` on J4/K4 — a number reported as something it was not

The adapter emitted **7.46%** as a content comparison between two memory dumps. It was
the difference in *volume* (228 versus 211 facts), not a comparison of content: the
adapter expected a `text` field while those dumps used `memory`, so no fact text was
compared at all. The valid content comparison, computed separately, is 98.61% exact
symmetric difference.

The adapter was later fixed to accept either field and to exit non-zero on an
unrecognised shape rather than substituting an empty string. The published J4/K4 numbers
were **not** recomputed through the fixed adapter; they remain as produced.

**Verifiability: documented in [`RESULTS_mem0_J4K4.md`](RESULTS_mem0_J4K4.md), published
in this repository.**

### 4. `canary_01` — an integrity counter contradicting its own manifest

The bundle's final JSON carried an embedded field `integrity.verified = 31`. Independent
verification of the same manifest gave **32** entries, 32 verified, 0 mismatches. Stale
metadata, no effect on any measured value.

**Verifiability: bundle exists in the run archive, not published here.**

### 5. `scoring_05` — a run summary contradicting itself on its own attempt count

The final JSON records, in one block:

```json
"logical_calls": 40,
"actual_attempts": 40,
"retries": 0,
...
"429": 1,
"queue_exceeded": 1
```

`retries: 0` and `429: 1` cannot both be true of the same run. The raw log shows prompt
15 in BA order, attempt 1 returning HTTP 429 `queue_exceeded`, and attempt 2 returning a
valid verdict. The correct technical figures are 40 logical comparisons, **41 actual
attempts, 1 controlled retry**.

The retry itself was handled correctly — the failed attempt produced no judgment, was
logged to a separate technical-error file, and did not enter `calls.jsonl`, so no
selection between two judgments took place and the 40 scientific comparisons are
unaffected. What was wrong is the field named `actual_attempts`, which did not report
actual attempts.

**Verifiability: bundle exists in the run archive, not published here.**

## What this supports

Four of the five would have passed unnoticed by reading the summary. Three were found
only because a value was recomputed from raw artifacts by a different implementation than
the one that produced it, and two of those three changed a formal verdict.

The pattern that survives the ten-bundle recount is narrower than "summaries are
unreliable." Scientific counters held everywhere they were checked. What did not hold was
everything adjacent to them: an attempt counter that contradicted a rate-limit counter in
the same JSON block, an integrity field one entry behind its own manifest, a classifier
that mapped a tie to a win in one position only, a parser stricter than its own
specification, and an adapter reporting a volume difference as a content comparison. None
of these is a measurement. All of them can change what a measurement means.

The practical rule this justifies is narrow and cheap: a summary is a convenience, not
evidence; the artifact is the evidence; and a number that has never been recomputed by a
second implementation should be treated as unverified regardless of how carefully the
first one was written.

## Verifiability status, stated plainly

| case | primary artifact | where |
|---|---|---|
| `calibration_04` | **partial** | faulty code survives in `codex/src/scoring04.py`; raw verdicts destroyed |
| `gptoss_probe_02` | **destroyed** | deleted in the same cleanup as `calibration_04` |
| `compare_dumps.py` J4/K4 | exists | published, `RESULTS_mem0_J4K4.md` |
| `canary_01` | exists | run archive, not published |
| `scoring_05` | exists | run archive, not published |

Only one of the five is checkable from this repository as it stands. Two were lost in a
single cleanup of five early bundles; of those two, one left its defective code behind and
one left nothing.
