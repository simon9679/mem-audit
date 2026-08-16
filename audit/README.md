# `audit/` — external audit of Mem0 (and one judge-side control)

This folder is the evidence bundle behind the "external audit" section of the top-level
[`../README.md`](../README.md). Part of this work is pre-registered before the run (the `PREREG_*`
files and the runs they gate); part is findings that surfaced later, on re-checking the artifacts
(`FINDINGS_summary_vs_raw.md`, the canary confidence-interval mismatch). Most headline numbers
recompute from artifacts published here — the `results/` analysis JSONs and, for the arena
order-effect run, its 60 raw judgments and manifest — while a few need data kept outside this
repository (the raw H2/I2 dumps and part of the J4/K4 artifacts) and cannot be recomputed from the
repo alone. Files are grouped below by role.

> The `*.py` files in this directory are **run harnesses** — one script per ingest / probe / run,
> not an importable library. They exist to reproduce a specific measurement, not to be depended on.

## 1. Main report

- [`AUDIT_mem0.md`](AUDIT_mem0.md) — the full write-up: two silent-write-loss mechanisms and a
  provider-dependent loop between them on mem0ai 1.0.11 (all fixed in 2.x) and, on the current
  release, ~9% exact (byte-identical) extraction reproducibility at `temperature=0`. Sections 1–9,
  with the manifest in §7.

## 2. Mem0 measurements

- [`FINDINGS_silent_loss.md`](FINDINGS_silent_loss.md) — **two** mechanisms by which Mem0 silently
  drops a write, plus a provider-dependent loop between them (caller told success, nothing stored);
  all confirmed fixed in mem0ai 2.x.
- [`RESULTS_mem0_HI_2x.md`](RESULTS_mem0_HI_2x.md) — H2↔I2 on 2.0.17: exact agreement about **9%**;
  at cosine 0.72 agreement about **22%** (symdiff 77.98%), and on that same metric the prefix curve
  runs 0 → 26.3 → 63.2 → 73.8 → 78.0% across sessions.
- [`RESULTS_mem0_J4K4.md`](RESULTS_mem0_J4K4.md) — J4↔K4, a configuration replication (`max_tokens=4000`,
  `reasoning_effort=low`): byte-for-byte agreement **~1.4%** (6 of 433 union facts), volume divergence
  7.46% — a second measurement, not a generalization beyond the tested dialogue, model, and provider.
- [`RESULTS_mem0_maxtokens.md`](RESULTS_mem0_maxtokens.md) — truncation fix (run F): `max_tokens`
  2000→16000 takes sessions-clean from 11/33 to **33/33**, 0 truncations. The default-config loss is a `max_tokens` artefact.
- [`RESULTS_mem0_symdiff.md`](RESULTS_mem0_symdiff.md) — Mem0 1.0.11, session 2: full-dump
  instability **~64–76%**, cleaned symdiff **17.4%** at every threshold.
- [`RESULTS_mem0_retrieval.md`](RESULTS_mem0_retrieval.md) — retrieval-divergence clean test
  **BLOCKED on budget, not run**; `search()` verified embed-only (zero LLM / zero Cerebras quota).

## 3. Instrument validation

- [`PROBE_symdiff_probe.md`](PROBE_symdiff_probe.md) / [`_v2`](PROBE_symdiff_probe_v2.md) —
  falsification checks for `symdiff_probe.py` (blob `17afd30…` identical across both runs); documents the ISSUEs the probe surfaces on itself.
- [`PROBE_symdiff_probe_REVIEW.md`](PROBE_symdiff_probe_REVIEW.md) — hand review of check #3
  (word-permutation criterion): it **failed** the strict `paraphrase < permutation` ordering, recorded rather than smoothed over.
- [`canary/`](canary/) — memory-vs-no-memory control, delta_correct **8/20**, verdict **PASS**;
  published CI [2, 13] does not reproduce (recomputed [4, 12], narrower — the published interval is
  wider and thus more conservative, so nothing is inflated).
- [`arena/`](arena/) — judge answer-position order effect, balanced within-run: **M1 = 7/20**
  cross-order vs **M2 = 0/20** same-order, verdict **INCONCLUSIVE**. Not an Arena-Hard (Bradley–Terry) audit.
- [`FINDINGS_summary_vs_raw.md`](FINDINGS_summary_vs_raw.md) — five cases where an automated
  summary disagreed with its own raw artifacts; a ten-bundle recount matched on every scientific
  counter, so the disagreements are all in technical accounting, integrity metadata, and classifier logic.

## 4. Pre-registrations (committed before any number)

- [`PREREG_HI.md`](PREREG_HI.md) / [`PREREG_HI_2x.md`](PREREG_HI_2x.md) — the H/I and H2/I2
  reproducibility pairs.
- [`PREREG_J4K4.md`](PREREG_J4K4.md) — the second-config reproducibility pair.
- [`PREREG_mem0_maxtokens.md`](PREREG_mem0_maxtokens.md) — the `max_tokens` fix + ceiling curve.
- [`PREREG_mem0_symdiff.md`](PREREG_mem0_symdiff.md) — the symmetric-difference re-check.
- [`PREREG_mem0_retrieval.md`](PREREG_mem0_retrieval.md) — the retrieval-divergence test.
- [`PREREG_mem0_constrained.md`](PREREG_mem0_constrained.md) — the constrained-ingest variant.
- [`PREREG_metric_entity_swap.md`](PREREG_metric_entity_swap.md) — the entity-swap metric guard.
- Arena order effect prereg lives with its bundle: [`arena/PREREG_arena_order_effect_balanced.md`](arena/PREREG_arena_order_effect_balanced.md).
