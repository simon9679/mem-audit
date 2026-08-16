# Mem0 silently drops writes — two mechanisms and a provider-dependent loop (issue-grade)

The headline result of this audit is not a symmetric-difference number. It is that
**Mem0 has two mechanisms that silently fail to store a memory, plus a provider-dependent
loop between them** — the caller is told the write succeeded, and it did not. Both mechanisms
occur in the same update-decision stage, which returns the full accumulated memory list on
every turn, and both are silently collapsed into an apparently successful write. Their
immediate triggers differ: output truncation against the cap, and a swallowed transport
error. One of the two was found *by accident*.

## How it was found (worth stating)

None of this came from bug-hunting. It fell out of an invariant we imposed for a
completely different reason — **"never checkpoint a partially-processed session"**
— added so a *resumable* run would be byte-equivalent to a continuous one. To
honour it we had to ask, per session, "did the write actually fully happen?" —
and the answer exposed a failure mode nobody was looking for. A requirement for
**reproducibility surfaced a latent defect in a third-party system**, demonstrated
rather than asserted. That is the methodology's own claim about itself, holding on
someone else's code.

## The structural root

Mem0's update-decision step returns the **entire accumulated memory list every
turn** (each fact + an ADD/UPDATE/DELETE/NONE event). Output therefore grows
linearly with the store (~55 chars ≈ ~14 tokens per stored fact, measured). This
one O(store) call is where both failures land.

## Path 1 — truncation against the output cap

The growing update output overruns `max_tokens` (mem0 default **2000**) at a
store of **~25–45 facts** (formula and cross-check in `RESULTS_mem0_maxtokens.md`;
`finish_reason='length'`). The JSON is cut mid-structure → mem0 logs
`Invalid JSON response` → empty actions → **the turn's facts are dropped.**
Reached on any conversation past a few dozen memories. *Leaves a trace* (a
parse-error log).

## Path 2 — swallowed 429 (more severe)

On a rate-limit — routine on free tiers, possible on any tier — the
update-decision LLM call returns HTTP 429. Mem0 **catches it internally**
(`logger.error("Error in new memory actions response: …")`), sets the response
empty, and `add()` **returns success.** The library reports the memory was stored;
it was not. Unlike Path 1 there is no parse error — the failure arrives from the
network and **dissolves into a single log line the application never sees.** A
caller has no signal at all that the write was lost.

This is the one found via the reproducibility invariant: a session whose update
call was swallowed logs as "ok" with only **one** LLM call recorded instead of
two — the tell that its reconciliation never ran.

## Path 3 — provider-dependent loop: the fix for Path 1 provokes Path 2

Raising `max_tokens` (2000 → 16000) removes truncation. But Cerebras **reserves quota by
`max_completion_tokens`, not by actual output.** A full 33-session ingest at 16000 reserves 33·2·16000 ≈
**1.05 M tokens** — the entire daily free-tier budget — though it *generates* only
~140 k. Exhausting the day's budget then makes every subsequent call 429, i.e.
**Path 2.** So the natural fix for silent-loss-by-truncation directly causes
silent-loss-by-429. Each link is measured, not inferred.

## Why this matters more than a symdiff

- Two runs of the same dialogue diverge in storage — but *why* they diverge is the
  product bug: **facts are dropped without error.** (And it reaches retrieval:
  `RESULTS_mem0_retrieval.md` shows two loss-afflicted runs return different,
  equally-relevant top-5 for all 20 questions — the loss is not cosmetic.)
- Path 2 is provider- and model-independent: it is a swallowed transport error,
  not a generation-quality issue. Any deployment that ever hits a 429 loses
  writes silently.
- The two mechanisms and the provider's reservation policy form a loop with no free corner:
  small cap → truncation; large cap → quota-reservation → 429 → swallowed loss.

**Fix direction for Mem0 (for the issue):** the update call must not be O(store)
(don't rewrite the whole memory list per turn), `add()` must surface a failed or
truncated update-decision as an error instead of returning success on empty
actions, and reservation cost should track expected output, not `max_tokens`.
