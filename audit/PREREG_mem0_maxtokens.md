# PREREG — Mem0 clean stability via raised max_tokens (session 4, revised)

*Registered BEFORE runs F/G produce any dump. Ranges. Not edited once numbers
exist. Supersedes the constrained-decoding approach (PREREG_mem0_constrained.md):
that run falsified its own "0 failures" prediction and, via finish_reason='length',
revealed the real cause — truncation, not decoding mode.*

## Question

Sessions 2/4 established that Mem0's "JSON failures" are **output truncation**
(`finish_reason='length'`) of its whole-memory update call against
`max_tokens=2000`, not malformed JSON and not decoding mode — a
**provider-independent, payload-vs-cap** limit. So flip the one knob that
actually matters: **max_tokens 2000 → 16000**, plain `json_object`, everything
else identical to A/B (model, temp 0, prompts, 12 s pacing, no retries). With
truncation gone, get the clean two-ingest stability number the whole exercise was
for — and the store→output-length curve that says where the (moved, not removed)
ceiling now sits.

## Depth smoke already passed (before this registration)

Sessions 0–15, plain json_object, max_tokens=16000: **0 truncations, 0 JSON
failures.** Store→output (update calls) grew linearly, store 0→81 giving content
1188→~7000 chars, all `finish_reason='stop'` — headroom at 16k through depth 15.

## Predictions (before numbers)

- **JSON failures F, E: 0. Truncations: 0** through the full 33 sessions — the
  load-bearing prediction. Risk noted: the update payload keeps growing; if a
  late session (store ≳ 150) still overruns 16k **tokens** (content + gpt-oss
  reasoning), n_truncations > 0 and the curve names where. Predict **0–2**
  truncations across all 33 (near-zero, with a small tail risk at max depth).
- **Volumes |F|, |G|: 120–190 facts each** (all 33 sessions now complete vs ~11
  in A; smoke: store 81 at session 15), |F| ≈ |G| within ~15 %.
- **No cleaning step** — with ~0 truncation there is nothing to drop; the full
  dump is the clean measurement.

**F vs G — full symdiff (all 33 sessions complete):**

| threshold | predicted symdiff% |
|---|---|
| exact | 8–25 |
| 0.60 | 6–22 |
| 0.72 | 7–24 |
| 0.82 | 8–25 |

Reasoning: temp 0 + all sessions completing + no store contamination (the source
of A/B cleaned's 17.4 % residual) should give the most stable pair yet — at or
below A/B cleaned's 17.4 %, driven only by any genuine Cerebras non-determinism
and volume-mismatch orphans. Roughly flat across thresholds (matches mostly
byte-identical, as in A/B cleaned). If F↔G ≫ 17.4 %, something beyond truncation
adds instability at full depth; if ≈ 0, Mem0's logic is essentially deterministic
once nothing truncates.

**Prefix curve** (symdiff at 0–4, 0–9, 0–16, 0–24, 0–32): low throughout, mild
rise with depth (more update decisions = more chances to diverge). 0–4 near the
F↔F floor, rising to the full value by 0–32.

**Store→output curve**: content length rises ~linearly with store size; extended
to 33 sessions it predicts the token budget at max depth and therefore the
max_tokens at which truncation would return — the number for a Mem0 issue.

**Control:** F↔F must be 0 % at every threshold.

## Headline the summary must answer

Four numbers: Cerebras plain-2k full **75.6** / A-B cleaned **17.4** / Cerebras
16k full **F↔G** / F↔F **0** — and the plain statement of how many points of the
observed 75.6 % instability the single max_tokens change removes, plus where
Mem0's silent memory ceiling sits (the curve) as a separate, model-independent
finding.
