# PREREG — Mem0 symdiff re-check (session 2)

*Registered BEFORE any ingest completes. Predictions are ranges (the smoke n is
tiny and high-variance). Not edited once real numbers exist — the prediction/fact
gap is the result, fixed, not smoothed.*

## Question

Reproduce session 1's measurement on a different system: **Mem0**. Ingest the
same 33-session dialogue (`p8`) twice under different user_ids into fresh
collections, identical config, same session order. Measure the symmetric label
difference between the two dumps with the same `symdiff_probe.py`, unchanged.

## System under measurement (unmodified)

- Mem0 (mem0ai 1.0.11), vector store **chroma (local)**.
- Embedder **sentence-transformers/all-MiniLM-L6-v2** (same embedder the probe
  uses — one embedding space for both mem0's own dedup and this measurement, so
  a divergence has one source, not two).
- Judge **Cerebras `gpt-oss-120b`, temperature 0**, via litellm (the openai
  provider sends an OpenAI-only `store` field Cerebras 400s on).
- **Pacing** `min_request_interval = 12.0` s (from mem-audit's own providers.py
  cerebras preset). A throttle, not a retry: changes no model input, only call
  spacing. Purpose: keep the free tier from 429-ing. Actual value used is
  recorded in `run_log.json`.

## Two failure modes, attributed separately (the third decomposition level)

- **JSON-parse failure** — judge answered with malformed JSON; mem0 logs
  `Invalid JSON response`; that session yields ~0 facts. Model behaviour →
  measured, not retried.
- **Transport (429)** — model never answered; free-tier queue rejected the
  request. Carries no information about Mem0 → paced away; if it still escapes,
  the session is flagged transport-corrupted in its own counter.

`symdiff` is computed **twice**:
- **full** — both complete dumps (what a user actually gets).
- **cleaned** — restricted to sessions that parsed AND were transport-clean in
  *both* runs. The full−cleaned gap is the contribution of ingest noise (parse +
  transport) to the observed instability. Small gap → divergence is semantic;
  large gap → much of the "memory instability" on this free stack is data loss at
  the parse/transport layer, a separately publishable finding.

## TBG baseline (session 1, for context — not a Mem0 prediction)

Two ingests of the same p8 dialogue through the TBG belief-graph extractor,
`|A|=|B|=50` short labels (≤50 chars), 22 orphans per side:

| threshold | exact | 0.60 | 0.72 | 0.82 |
|---|---|---|---|---|
| TBG symdiff% | 94.74 | 61.11 | 73.42 | 79.52 |

**Cross-system caveat that shapes the predictions below:** TBG labels are short
phrases; **Mem0 facts are full sentences.** MiniLM's baseline cosine between
full sentences of the same genre is higher than between short phrases, so at any
fixed cosine threshold Mem0's symdiff% will read *lower* than TBG's for
equally-divergent content — an artifact of surface length, not of Mem0 being more
stable. This is exactly why the negative control is mandatory: it calibrates what
"two genuinely different corpora" scores on this same probe + embedder.

## Predictions (ranges, before numbers)

### Volumes and failures (per 33-session p8 run)
- **|A|, |B|**: 80–170 facts each (mem0 is ADD-mostly; growth sublinear via
  update/dedup). Predict |A|≈|B| within ~20% of each other.
- **JSON-parse failures**: 1–10 sessions per run (smoke: 2/3 then 0/2 — wide).
- **Transport-429 (after pacing)**: 0–4 sessions per run (pacing should absorb
  most; residual from genuine free-tier congestion).
- **clean subset** (parsed+clean in both): ~18–31 of 33 sessions.

### A vs B — the measurement
| threshold | full symdiff% | cleaned symdiff% |
|---|---|---|
| exact | 95–100 | 95–100 |
| 0.60 | 35–58 | 30–55 |
| 0.72 | 50–70 | 45–66 |
| 0.82 | 65–83 | 60–80 |

Reasoning: full-sentence facts almost never byte-match → exact ~stays near 100.
Two independent ingests of the *same* dialogue share much content, so cosine
thresholds collapse symdiff well below exact (as with TBG). Cleaned ≤ full at
each threshold; predicted gap **0–15 pp** — the open question is whether it is
near 0 (divergence is semantic) or large (parse/transport noise dominates).

### A vs C — negative control (p8 vs p2, different dialogue)
Expect near-total divergence, but watch the MiniLM full-sentence baseline:
- exact: 99–100%
- 0.82: 95–100%
- 0.72: 88–99%
- 0.60: **80–95%** (if this dips much below ~85%, MiniLM's full-sentence
  baseline is inflating apparent overlap between unrelated corpora, and the A–B
  0.60 number must be read against this floor, not against 0%).

### A vs A — positive control
0% symdiff at **every** threshold, exactly. Anything else means the greedy
matcher is broken on the new full-sentence input type.

## Done when
Three probe tables (A–B, A–C, A–A) obtained; positive control = 0; negative
control named as a number; full vs cleaned compared; predictions above set
against fact.
