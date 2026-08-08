# PREREG — extraction reproducibility on mem0ai 2.0.17 (H2 ↔ I2)

*Registered before the run, before any H2/I2 number exists. Frozen.*

## What is measured

The one open question the 2.x refactor does not touch: **is Mem0's fact extraction
reproducible at `temperature=0`?** Two clean complete ingests (H2, I2) of the same
33-session `p8` dialogue on **mem0ai 2.0.17**, then `symdiff_probe.py` (unchanged) on
the two dumps.

Config: mem0ai 2.0.17, Chroma local, HuggingFace `all-MiniLM-L6-v2` embedder,
litellm → Cerebras `gpt-oss-120b`, `temperature=0`, **single-call additive
extraction** (`ADDITIVE_EXTRACTION_PROMPT`), `max_tokens=2000` (output is now only the
new facts, so a low cap is safe and cheap), 15 s pacing, resumable runner.

## This is NOT a direct comparison to 1.0.11 — stated here, before the run

Several things changed between 1.0.11 and 2.0.17 at once: two-call → **single-call**
extraction, the old update-decision prompt → **`ADDITIVE_EXTRACTION_PROMPT`**, and
`get_all` default `top_k` (now 20). So if divergence differs from the 1.0.11 numbers
(exact 54.55 %, 0.72 34.98 %), it **cannot be attributed to any single change**. The
1.0.11 numbers are quoted only as **context**, never as a baseline. What is measured
here is the reproducibility of **2.0.17 as it is**, on its own terms.

## Prediction (before numbers)

- **Volume divergence |H2| vs |I2|: < 15 %.**
- **Symdiff:** exact **40–60 %**, 0.60 **20–40 %**, 0.72 **25–45 %**, 0.82 **30–50 %**.
- i.e. expect divergence to **stay substantial** (0.72 ≳ 25 %), because extraction
  non-determinism at temp 0 is a property of the LLM, not of the pipeline the refactor
  changed.

If wrong in either direction, recorded as wrong, unedited.

## How each outcome reads (fixed now)

- **Divergence stays substantial** (~1.0.11 order): reproducibility did **not** improve
  after an architectural refactor — because it was never in the architecture; it is in
  the LLM extraction itself. This would be the cleanest result of the whole audit.
- **Divergence drops sharply** (0.72 ≪ 15 %): the change (single-call /
  `ADDITIVE_EXTRACTION_PROMPT`) improved reproducibility — the cause is then likely the
  **prompt**, which is a separate question that one pair of runs cannot settle
  (it would need prompt-level ablation).

Both are publishable; neither is the hoped-for one.

## Methodology guards (registered, because they can silently ruin the run)

1. **`get_all` top_k truncation guard.** `get_all` in 2.0.17 defaults to `top_k=20`;
   dumping with the default would silently cap the store at 20 facts — the same class
   of silent-loss this audit is about. The harness calls `get_all(top_k=100000)` (far
   above the ~180 expected) and **asserts the returned count ≠ top_k**; equality to the
   ceiling means truncation, not a result, and aborts.
2. **Single-call sanity.** The harness logs the number of LLM calls per session. 2.x is
   read as one extraction call per `add()`. If any session shows **≠ 1** LLM call, the
   run stops and reports — it would mean the installed package does not match the code
   we read, and that must be known before a full run, not after.

Control: **H2 ↔ H2 = 0 %** at every threshold.
