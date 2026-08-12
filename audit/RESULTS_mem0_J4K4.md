# RESULTS — a second reproducibility pair on mem0ai 2.0.17 (J4 ↔ K4)

PREREG: `PREREG_J4K4.md`, registered before any number. H2/I2 (`RESULTS_mem0_HI_2x.md`)
measured run-to-run reproducibility once, at `max_tokens=2000`. This is the same
question — **is Mem0's fact extraction reproducible at `temperature=0`** — under a
**different** working configuration, to test whether the H2/I2 result was specific to
that setting or holds more generally on 2.0.17.

## Configuration

mem0ai **2.0.17**, Chroma local, HuggingFace `all-MiniLM-L6-v2` embedder, litellm →
Cerebras `gpt-oss-120b`, `temperature=0`, single-call additive extraction, **`max_tokens=4000`,
`reasoning_effort=low`** (both differ from H2/I2), windowed resumable runner, ≥60 s between
windows of 4 sessions. Two runs J4, K4: same 33-session `p8` dialogue, fresh collections,
same order. Metric: `symdiff_probe.py`, unchanged — invoked through a new adapter,
`codex/analyze_pair.py`, that explicitly requires the `memory` field 2.x dumps use (see
"Methodological note" below; this is **not** `audit/compare_dumps.py`).

`reasoning_effort=low` is a Cerebras-specific parameter mem0ai 2.0.17 does not forward on
its own; two earlier calibration attempts at the default reasoning level truncated
(`finish_reason=length`) even at `max_tokens=4000`, before this parameter was found and
applied. Both runs made exactly one LLM call per session, every call `finish_reason=stop`,
33/33 sessions complete, no swallowed errors.

## Numbers

J4 = 228 facts, K4 = 211 facts (**volume divergence 7.46 %**). Positive control
**J4 ↔ J4 = 0.00 %** at every threshold.

| J4 ↔ K4 | exact | 0.60 | 0.72 | 0.82 |
|---|---|---|---|---|
| matched | 6 | 183 | 155 | 108 |
| symdiff % | 98.61 | 28.52 | 45.42 | 67.37 |
| Jaccard | 0.0139 | 0.7148 | 0.5458 | 0.3263 |

**Two runs of the identical configuration at temperature 0 agree byte-for-byte on only
~1.4 % of facts** (6 of 433 union facts) — a wider exact-level gap than H2/I2's ~9 %.
At the loosest cosine threshold (0.60) agreement is substantially higher (71 % Jaccard)
than H2/I2 saw at its comparable threshold, consistent with — but not proof of — more
paraphrase-level restatement in a larger store; several things changed between the two
pairs at once (`max_tokens`, `reasoning_effort`, resulting store size), so this shape
difference is reported as an observation, not attributed to any one cause.

Retrieval over the same 20 frozen questions, top-5, zero LLM: **0/20** questions returned
an identical top-5, mean per-question Jaccard **0.0111**, pooled symdiff at cosine 0.72
**51.67 %** (Jaccard 0.4833) — divergence reaches retrieval here as it did in H2/I2.

## Predictions vs facts (PREREG not edited)

| quantity | predicted | actual | verdict |
|---|---|---|---|
| volume divergence | < 15 % | 7.46 % | **hit** |
| symdiff exact | 75–100 % | 98.61 % | **hit** |
| symdiff 0.72 | 60–90 % | 45.42 % | **miss (below range)** |
| J4 ↔ J4 control | 0 | 0 | **hit** |
| retrieval, identical top-5 | ≤ 2 of 20 | 0 of 20 | **hit** |

The 0.72 miss is not read as J4/K4 being "less carefully calibrated" than H2/I2: H2/I2's
own pre-registered 0.72 range (25–45 %) also missed, in the opposite direction (actual
77.98 %). Two independent pairs, two misses on the same threshold, in opposite directions —
recorded as evidence that this quantity is hard to predict in advance from one prior
measurement, not as a property of either run.

## Interpretation

J4/K4 replicates the qualitative core of H2/I2 — two clean runs of the same configuration
at `temperature=0` produce substantially different memory, and the difference reaches
`search()` — under a **different working configuration** (`max_tokens`, `reasoning_effort`,
and a resulting store roughly 3× the size). This moves the finding from a single
measurement to a **configuration replication**: the instability is not an artifact of one
specific `max_tokens` setting on 2.0.17.

## What this does not establish

- **Not a dialogue-length or store-size causal claim.** J4/K4 differs from H2/I2 in
  several variables at once (`max_tokens`, `reasoning_effort`, launch time, resulting
  store size). The pattern "larger store → lower exact match, higher loose-cosine match"
  is consistent with a paraphrase-density hypothesis but is not isolated by this
  comparison alone.
- **Does not replicate the H2/I2 prefix curve.** J4/K4 was not measured at intermediate
  session counts, so it says nothing about *where* divergence accumulates across the
  dialogue — only that it is present in the final dump and in retrieval.
- **n = 1 dialogue, one model, one provider, one `reasoning_effort` setting.** As
  throughout this audit.

## Methodological note: `audit/compare_dumps.py` does not apply to 2.x-style dumps

An initial run through the existing `audit/compare_dumps.py` returned a symdiff of 7.46 %
— numerically identical to the volume-divergence figure above, and not a content
comparison. `compare_dumps.py` reads a `text` field; Mem0 2.x dumps of this shape store
facts under `memory`, so every extracted string was silently empty, and the "7.46 %"
was an artifact of comparing two lists of blank strings of different lengths, not of
comparing content. This was caught before being reported as a finding, not after.
`audit/compare_dumps.py` should be treated as **validated for `text`-keyed dumps only**;
a schema check that fails loudly on an unrecognized shape, rather than silently
substituting an empty string, is a needed fix and is not yet made in the committed
adapter (see `codex/analyze_pair.py` for the workaround used to produce this file's
numbers).

## Manifest (number → file → SHA-256)

Raw data outside the repository (produced locally; not yet published as a release
package — see the note on `mem-audit-release` in `AUDIT_mem0.md` §7 regarding what "in
repo" verification currently covers).

| numbers | file | size (B) | SHA-256 | produced by |
|---|---|---|---|---|
| J4↔K4 dump-level symdiff, matched counts | `analysis_J4K4.json` | 2956 | `0778a9b979c995659113ee5d111af113c1b409f8fd468b7eecb0192fb6e2e6f8` | `codex/analyze_pair.py` |
| J4↔K4 retrieval, pooled + per-question | `retrieval_J4K4.json` | — | `4d39ef1a3f3661fca0875742adabd74b28a2d5f377f614bda39d72d4b954530a` | `codex/analyze_retrieval.py` |

Verify the published result files from the manifest directory:
```bash
cd audit/results
sha256sum -c MANIFEST.sha256
```

Full run artifacts, per-session logs, frozen config, and the bundle-level SHA-256 manifest
are recorded in `codex/J4K4_FINAL/README_J4K4.txt` and `codex/J4K4_FINAL/BUNDLE_MANIFEST.sha256`,
pending a decision on whether that bundle is published as a repository release (not yet
done as of this writing).

Reproduce the dump-level comparison (once raw dumps are published):
`python codex/analyze_pair.py --j dump_J4_p8.json --k dump_K4_p8.json --out analysis_J4K4.json`
