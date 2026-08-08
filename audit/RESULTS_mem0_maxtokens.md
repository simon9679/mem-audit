# RESULTS — Mem0 max_tokens fix + memory-ceiling curve (session 4)

PREREG: `PREREG_mem0_maxtokens.md` (registered before any dump). One knob changed
vs session 2's A/B: **max_tokens 2000 → 16000**, plain `json_object`, same model
(cerebras/gpt-oss-120b), temp 0, prompts, 12 s pacing, no retries.

## 1. The truncation fix works (run F)

| run | max_tokens | facts | truncations | JSON-fail | sessions clean |
|---|---|---|---|---|---|
| A (session 2) | 2000 | 57 | ~all fails were length | 22/33 | 11/33 |
| **F** | **16000** | **134** | **0** | **0** | **33/33** |

At 16 000 every one of the 33 sessions completes, every update call
`finish_reason='stop'`, store reaches 131 facts with no loss. The default-config
data loss (⅔ of sessions in A) is entirely a `max_tokens` artefact, confirmed.

## 2. F↔G stability number — UNOBTAINABLE on this stack (honest negative)

G never completed. F's 33 large-output sessions saturated the Cerebras free-tier
**org-level** rate limit; every G attempt (incl. a second key on the same
account, and one after a full 60-minute cooldown at 25 s pacing) 429-cascaded — a
per-organization throttle, not a per-key quota. The best G got was **63 facts
from 12 transport-clean sessions (0 truncation, 0 JSON-fail on those)**; 21/33
sessions were 429'd.

The probe was run anyway, and the numbers say **why they are not the stability
number** (F↔F control = 0.00 % at every threshold, so the matcher is sound):

| comparison | exact | 0.60 | 0.72 | 0.82 | note |
|---|---|---|---|---|---|
| F↔G full (134 vs 63) | 95.8 | 71.2 | 76.9 | 83.4 | dominated by |F|=134 vs |G|=63 |
| F↔G cleaned (12 both-clean sessions) | 92.7 | 50.6 | 56.1 | 68.9 | still contaminated (below) |
| F↔G prefix 0–8 (both ran 0–8 in full) | 91.7 | 44.8 | 49.3 | 63.2 | 41 vs 63 facts on the **same 9 sessions** |

**These measure completeness-asymmetry, not extraction determinism.** The
prefix-0–8 row is the proof: F and G ran sessions 0–8 identically and
consecutively, yet F's final dump carries **41** facts from them and G's **63** —
because Mem0 is **stateful**: F's later sessions (9–32) UPDATE/DELETE-edited its
early-session facts, G (which stopped at ~session 8 plus three stragglers) did
not. So any two runs of **unequal completeness diverge by construction**, and F↔G
here is that artefact, not a stability signal.

**Consequence — a real finding in itself:** on the free tier, Mem0's own
stability is *unmeasurable*, because it needs two *complete* 33-session runs and
a single complete run already exhausts the org rate limit — and even given two,
Mem0's whole-history rewriting amplifies any single hiccup (a truncation, a 429)
into whole-dump divergence. The cleanest determinism hint remains A/B's cleaned
subset (17.4 %, mostly byte-identical) on early, small-store sessions — but it is
thin and subject to the same statefulness caveat. A clean number would require a
paid tier (two uninterrupted runs) or equal-length truncated runs; not available
here. PREREG's 8–25 % prediction is therefore **untestable**, not confirmed or
refuted — recorded as such.

## 3. The memory-ceiling curve (independent finding, from F's instrumentation)

Mem0's update-decision call returns the **entire accumulated memory list every
turn**, so its output length grows linearly with the store. From F's 31 update
calls:

| store (facts) | output (chars) | ≈ content tokens | finish |
|---|---|---|---|
| 0 | 1566 | ~390 | stop |
| 46 | 4111 | ~1030 | stop |
| 91 | 6918 | ~1730 | stop |
| 121 | 8433 | ~2110 | stop |

**Output ≈ 1566 + 55·n chars** for a store of `n` facts (~**14 tokens/fact**).

A per-update call spends, in tokens:
`total(n) ≈ 392 + 14·n + R`, where `R` = the gpt-oss **reasoning overhead**
(measured ≈ 900–1300 tokens, and *variable* turn to turn).

Truncation — Mem0 silently dropping the turn's facts — happens when
`total(n) > max_tokens`. Solving for the store at which the ceiling is hit:

> **n★ ≈ (max_tokens − R − 392) / 14**

Plug in your own `max_tokens`:
- **2000 (Mem0 default)** → n★ ≈ **25–45 facts** (R-variability sets the band).
- **16000** → n★ ≈ **~1000 facts**.

### Cross-check on A/B (free — data already collected, no new run)

Run A used the default 2000. Its cumulative store vs parse outcome:

| session | store before | outcome |
|---|---|---|
| 0–2 | 10→26 | ok |
| **3, 4** | **26** | **truncated** |
| 5–7 | 32→40 | ok |
| 8–10 | 40 | truncated |
| 11 | 49 | ok |

First truncation at **store 26**, intermittent through **store ~49** — dead
centre of the formula's 25–45-fact prediction for `max_tokens=2000`. And the
**intermittency is the mechanism, not noise**: in the boundary band the outcome
flips with `R` (reasoning length) that turn — high reasoning → truncate, low →
fit. That variable overhead *is* the run-to-run "extraction lottery" seen across
sessions 1–4: not stochastic extraction, but a deterministic output-growth curve
crossing a fixed token cap with a wobbling reasoning tax on top.

## 4. Headline

Independent of what F↔G turns out to be: **Mem0 has a silent, model-independent
memory-size ceiling.** Its whole-history update call grows ~14 tokens per stored
fact, so at the default `max_tokens=2000` the store stops absorbing new facts at
**~25–45 facts** — reached on any conversation past a few dozen memories — with
no application-visible error, only a log line. Raising `max_tokens` to 16000
moves the ceiling to ~1000 facts; it does not remove it (the call is O(store) by
construction). This is a direct issue for the Mem0 repository and a post in its
own right, and it is the same class of defect as the FactEngine fact-count
ceiling found in this project's own system — a structural limit masquerading as a
working one.
