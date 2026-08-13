# FINDING: canary bootstrap CI does not reproduce

## Summary

The 95 % confidence interval for `delta_correct` published in
`CANARY_FINAL.json` is **[2, 13]**. Paired bootstrap recomputation with the
same seed (20260811) and sample count (10000) yields **[4, 12]** across all
eight implementations tested. The point estimates and aggregates match exactly.

## Aggregates (match)

| statistic | CANARY_FINAL.json | recomputed |
|---|---|---|
| n | 20 | 20 |
| memory_correct | 11 | 11 |
| no_memory_correct | 3 | 3 |
| delta_correct | 8 | 8 |

## CI (mismatch)

| source | method | CI 95 % |
|---|---|---|
| CANARY_FINAL.json | "paired bootstrap percentile" | **[2, 13]** |
| recomputation (all paired variants) | paired bootstrap percentile | **[4, 12]** |
| recomputation (unpaired) | independent resampling of arms | [3, 13] |

## Implementations tested

All eight paired-bootstrap variants produce [4, 12]:

1. `numpy.random.default_rng(seed).integers` + `numpy.percentile` (method='linear')
2. `numpy.random.RandomState(seed).randint` + `numpy.percentile` (method='linear')
3. `random.choices` (stdlib) + sorted-index percentile
4. `numpy.percentile` method='lower'
5. `numpy.percentile` method='higher'
6. `numpy.percentile` method='nearest'
7. `numpy.percentile` method='midpoint'
8. `scipy.stats.bootstrap` (method='percentile', seed=20260811)

One unpaired variant (independent resampling of memory and no_memory arms with
`numpy.random.default_rng`) produces [3, 13].

## Interpretation

The published interval [2, 13] is **wider on both sides** than the recomputed
[4, 12]. The original publication is therefore more conservative (wider
uncertainty), not more optimistic. No published conclusion is inflated by this
discrepancy.

The PASS verdict (`delta_correct ≥ min_delta_correct = 8`) does not depend on
the CI at all. And the lower bound is positive in both versions ([2, 13] and
[4, 12]), so the qualitative conclusion — that `delta_correct` is
distinguishable from zero — holds under either interval.

## Probable cause

The source code that computed the bootstrap CI in `CANARY_FINAL.json` is not
present anywhere on disk. A full-text search for `bootstrap`, `percentile`,
`ci95`, and `delta_correct` across the entire repository and working tree
returned matches only in third-party `site-packages`; no project code
implements this calculation. It was a one-off computation in an AI-assistant
session and was not saved. The closest match to [2, 13] is unpaired
resampling [3, 13], but `CANARY_FINAL.json` declares the method as "paired
bootstrap percentile", so we cannot confirm which implementation was used.

## Disposition

`CANARY_FINAL.json` is published as-is with the original [2, 13]. The
recomputed [4, 12] is documented here as a reproducibility finding. The
recomputation script (`recompute_canary_ci.py`) is deterministic and runs on
the redacted verdict files without access to any p8 text.

## Provenance of CANARY_FINAL.json

The file `audit/canary/CANARY_FINAL.json` is a redacted copy of the original
produced during the canary run. One field was replaced:

| field | original value | published value |
|---|---|---|
| `inputs.j4_store` | local Windows path to `runs/J4/chroma` | `<J4_STORE>` |

No other fields were changed. All numbers, verdicts, the bootstrap method,
seed, sample count, and CI remain byte-identical to the original.

| version | SHA-256 |
|---|---|
| original (backup) | `d0dd332288ce23bf2f006421a41ae59e7007ef3f42f764c6b2f20a900a027c81` |
| published (j4_store redacted) | `4e67c5628423d9795333ae1bf1bc938c27009992b95ae7b7133e8d6808c036cd` |

Edited fields: `inputs.j4_store` only.

## Reproduce

```
python audit/canary/recompute_canary_ci.py audit/canary/raw_redacted
```

Expected output:
```
n=20  memory_correct=11  no_memory_correct=3  delta=8
bootstrap ci95 delta_correct: [4, 12]  (seed=20260811, samples=10000)
published ci95 in CANARY_FINAL.json: [2, 13]
```
