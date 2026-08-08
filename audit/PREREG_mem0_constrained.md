# PREREG — Mem0 + constrained decoding (session 4)

*Registered BEFORE runs D/E produce any dump. Ranges (the effect size is the open
question). Not edited once numbers exist.*

## Question

Sessions 1–3 measured Mem0 on Cerebras `gpt-oss-120b` with `json_object`
decoding: full-dump symdiff **75.6 %**, but two-thirds of sessions failed
JSON-parse; on the 5 sessions that parsed in both runs extraction was
**identical** (cleaned 17.4 %, and that residual was store contamination, not
drift). This session flips exactly one variable — **decoding mode** — to strict
`json_schema` constrained decoding on the *same* model, temperature, prompts, and
pacing. How much of the observed 75.6 % instability does that one switch remove?

## System (one change vs A/B)

Identical to session 2 (chroma local, HuggingFace MiniLM embedder, litellm →
Cerebras gpt-oss-120b @ temp 0, 12 s pacing, per-session metadata, JSON-fail
logger capture) **except** litellm.completion is intercepted to upgrade mem0's
`response_format={"type":"json_object"}` to `{"type":"json_schema","json_schema":
{...,"strict":true}}` — the facts schema for the extraction call, the memory
schema for the update call (told apart by the "smart memory manager" marker).
No prompt / model / temperature / retry change. Smoke (3 sessions): **0 JSON
failures** confirmed before this registration.

## Honest framing (not a fix of A/B)

Constrained decoding **intervenes in generation** — unlike pacing, which changed
no model input. So D/E is a **separate pair**, not a corrected A/B. Both results
stand side by side. The comparison is Cerebras-plain vs Cerebras-constrained,
same model.

## Predictions (before numbers)

- **JSON failures D, E: 0** (constrained decoding makes malformed JSON
  impossible by construction; smoke already 0/3). This is the load-bearing
  prediction — if it is not 0, the intervention failed and everything else is
  moot.
- **Transport-429 D, E: 0–3** (pacing; residual free-tier congestion).
- **Dump volumes |D|, |E|: 90–180 facts each**, and |D| ≈ |E| within ~15 %.
  (All 33 sessions now parse, vs ~11 in A/B, so more facts than A's 57; sublinear
  via update/delete consolidation. Smoke: ~5–7 facts per productive session.)
- **No cleaning needed** — with 0 parse failures there is nothing to drop; the
  full dump *is* the clean measurement.

**D vs E — full symdiff (all 33 sessions live):**

| threshold | predicted symdiff% |
|---|---|
| exact | 8–30 |
| 0.60 | 6–26 |
| 0.72 | 7–28 |
| 0.82 | 8–30 |

Reasoning: at temp 0 + constrained decoding, with every session parsing in both
runs and **no store contamination** (the source of A/B's 17.4 % residual), the
two ingests should be *more* stable than A/B cleaned — plausibly well below
17.4 %, approaching the A↔A floor if Mem0's logic is near-deterministic. Residual
divergence comes from (a) any genuine Cerebras non-determinism at temp 0, and (b)
volume mismatch creating orphans. Predicted roughly flat across thresholds
(matches will be mostly byte-identical, as in the A/B cleaned subset).

**Prefix curve** (symdiff on sessions 0–4, 0–9, 0–16, 0–24, 0–32): predicted
**low throughout, with a mild rise as store depth grows** — deeper stores mean
more update-decision calls, each a chance for the two runs to diverge. Predict
the 0–4 point near the A↔A floor (~0–10 %) rising to the full-run value (~8–30 %)
by 0–32. If it instead *stays flat near 0*, Mem0's update logic adds no
instability even at depth; if it *climbs steeply*, depth-driven divergence is a
real second-order effect.

**Controls:** D↔D must be 0 % at every threshold (matcher sanity on this input).

## Headline the summary must answer

Three numbers side by side — Cerebras full **75.6**, Cerebras cleaned **17.4**,
Cerebras+constrained full **D↔E** — and the plain statement: how many points of
the observed 75.6 % instability one switch (constrained decoding) removes, and
how much of what remains is Mem0's own logic vs model non-determinism.
