# PREREG — Mem0 retrieval-divergence test (session 5, step 3)

*Registered BEFORE running retrieval. Rule 7: test the product, not the mechanism.
Dump divergence is a storage property; it reaches the user only if it changes
what `search()` returns. This measures that. Not edited once numbers exist.*

## Why this is free

`mem0.Memory.search()` is embed-only — verified in the installed code:
`generate_response`/`self.llm` absent, `_search_vector_store` uses `embed` only.
The embedder is local HuggingFace all-MiniLM-L6-v2. **Zero LLM calls, zero
Cerebras quota.**

## Fixed inputs (locked before the run)

- 20 questions, taken from ES-MemEval's own p8 question set (81 available, first
  20). Verbatim list kept OUT of the repo (withheld-derived) at
  `mem0_maxtokens/retrieval_questions.json`.
  **sha256 = `5e51de93f63403d3a1b0467ae36e13f83aecacac68b53cd64b9cbaf5ecd73779`**
  (proves the list was fixed before running).
- Stores: F (max_tokens=16000, all 33 sessions) and G (max_tokens=6000; F/G max
  differ but every call `finish=stop`, so the cap never shaped output — stated
  openly, not hidden). Retrieval requires G to have completed all 33; if G is
  still transport-incomplete, this test is deferred and said so.

## Method

For each of the 20 questions: `search(q, user_id, limit=5, rerank=False)` (pure
vector top-k) against F's store and G's store. Pool the retrieved fact texts
(union over the 20 questions) for each store, then compare F-pool vs G-pool with
the **same** `symdiff_probe.py` at all four thresholds. Also report the mean
per-question exact top-5 overlap.

## Predictions (both quantities, before numbers)

Conditional on G completing all 33 sessions clean:

- **Dump F↔G symdiff** (whole stores): **10–35 %** (0.72). Two complete temp-0
  runs; residual from Cerebras run-to-run non-determinism + Mem0 update ordering.
- **Retrieval-surface symdiff** (what search actually returns): **predicted
  clearly LOWER than the dump number — roughly 40–70 % of it** (e.g. if dumps
  differ 25 %, retrieval differs ~10–17 %).

Reasoning: top-5 vector search pulls the most salient, most-reinforced facts,
which are the ones most likely to be extracted in both runs; the divergence
concentrates in the long tail of rarely-retrieved facts. So the storage
divergence should be **partly cosmetic** — present in the dump, largely absent
from what the user sees.

**Falsifiable reads:**
- Retrieval symdiff ≪ dump symdiff → divergence is cosmetic, does not reach the
  user → strong positive result for Mem0; the reproducibility "defect" is real
  in storage but harmless in product.
- Retrieval symdiff ≈ dump symdiff → divergence is real and product-facing →
  grounds to ask for credits and run the full eval (steps 4–6).
