# RESULTS — extraction reproducibility on mem0ai 2.0.17 (H2 ↔ I2)

PREREG: `PREREG_HI_2x.md`, registered before any number. This measures the one
question the 2.x refactor does not touch — **is Mem0's fact extraction reproducible
at `temperature=0`** — on the **current** release, after the refactor that removed
the three defects of §3.1–§3.3.

## Configuration
mem0ai **2.0.17**, Chroma local, HuggingFace `all-MiniLM-L6-v2` embedder,
litellm → Cerebras `gpt-oss-120b`, `temperature=0`, **single-call additive
extraction** (`ADDITIVE_EXTRACTION_PROMPT`), `max_tokens=2000`, 15 s pacing. Two
runs H2, I2: same 33-session `p8` dialogue, fresh collections, same order. Metric:
`symdiff_probe.py`, unchanged.

Both guards from the PREREG held: **every session made exactly one LLM call**
(single-call confirmed across all 66 sessions), and `get_all(top_k=100000)` never
returned exactly `top_k` (no silent dump truncation).

## Numbers

H2 = 65 facts, I2 = 68 facts (**volume divergence 4.4 %**). Positive control
**H2 ↔ H2 = 0.00 %** at every threshold.

| H2 ↔ I2 | exact | 0.60 | 0.72 | 0.82 |
|---|---|---|---|---|
| symdiff % | 90.98 | 65.66 | 77.98 | 83.33 |
| Jaccard | 0.09 | 0.34 | 0.22 | 0.17 |

**Two runs of the identical configuration at temperature 0 agree byte-for-byte on
~9 % of facts, and on ~22 % (Jaccard, cosine 0.72).** Retrieval over the 20 frozen
questions: pooled symdiff 68–91 %, per-question top-5 Jaccard **0.064**, **0/20**
questions returned an identical top-5. Amplification: diverging retrieved facts
mean cosine to the question **0.524** vs matched **0.530** (Δ +0.006) — diverging
facts are as on-topic as matched ones, so the difference is in valuable content,
not tail noise.

## The prefix curve (the main result)

Symdiff (cosine 0.72) restricted to sessions 0–k:

| 0–4 | 0–9 | 0–16 | 0–24 | 0–32 |
|---|---|---|---|---|
| **0.0** | 26.3 | 63.2 | 73.8 | 78.0 |

**On a short conversation Mem0's extraction is deterministic** — the first five
sessions are byte-for-byte identical between the two runs (all 11 shared exact
facts come from there). **Divergence appears with accumulated context and grows
with it**, reaching 78 % by session 32 with no sign of a plateau. This is a direct
empirical statement about *where* a memory layer starts to be unreliable: not on
short exchanges, but on the multi-session horizon, and worse the longer the history.

## Interpretation

The architectural refactor that removed §3.1–§3.3 did **not** make extraction
reproducible. Reproducibility is therefore **not in the architecture** — it is in
the LLM extraction step, which is stochastic at temperature 0 (the same model call,
run twice, yields different facts once the context is non-trivial). This is the
strongest result of the audit because it is not tied to a specific bug in a specific
version: it is a property of building memory on top of LLM extraction.

## Predictions vs facts (PREREG not edited)

| quantity | predicted | actual | verdict |
|---|---|---|---|
| volume divergence | < 15 % | 4.4 % | **hit** |
| symdiff exact | 40–60 % | 90.98 % | **miss (far high)** |
| symdiff 0.72 | 25–45 % | 77.98 % | **miss (~2× high)** |
| "stays ~1.0.11 order (≳25 %)" | substantial | much higher | direction of "substantial" right, magnitude badly under-predicted |
| H2 ↔ H2 control | 0 | 0 | hit |

Both the pre-registered guess (≈35 %, ~1.0.11 order) and the numeric prediction
(0.72 ≈ 25–45 %) were wrong — divergence is much larger. Recorded as-is.

## Limitations

- **Small base.** 2.x extracts far fewer facts (65/68) than 1.0.11 did (189/179).
  On ~65 items a symmetric-difference percentage is **more volatile** than on ~180;
  the 78 % figure must not be read out of that context. This was registered in the
  PREREG and is repeated here so a reader does not carry the number away alone.
- **No cross-version magnitude comparison.** 1.0.11 → 2.0.17 changed several things
  at once (single-call vs two-call, `ADDITIVE_EXTRACTION_PROMPT`, `get_all` default
  `top_k`), so the direction "2.x diverges more than 1.0.11" **cannot be
  attributed** and is not claimed. Only 2.0.17-as-such is measured here.
- **Shape observation (needs larger n).** As a shape only, not a magnitude: the
  1.0.11 prefix curve started at 23 % (0–4) and plateaued near 35 %; the 2.0.17
  curve starts at **0 %** and climbs to 78 % **without saturating**. So on 2.0.17 the
  early phase is cleaner and the late phase does not level off. Whether that shape
  (clean start, no plateau) is real or an artifact of the small base is **open and
  requires a larger n** (more dialogues, longer horizons). Noted as an observation,
  nothing more.
- **n = 1 dialogue, one model, one provider.** As throughout.

## Manifest (number → file → SHA-256)

Raw data outside the repo; `<2X>` is the local output directory. Computed once at
run completion, files unchanged since.

| numbers | file | size (B) | SHA-256 | produced by |
|---|---|---|---|---|
| H2 facts | `<2X>/dump_H2_p8.json` | 11123 | `4282711266d1d33c6de55d4127ff40555b991fe2d3cab676640cb39a423ca4c5` | `run_pair_2x.py` (mem0_resume_2x) |
| I2 facts | `<2X>/dump_I2_p8.json` | 12092 | `697f92f2b4ba9e3046a403da00cf2494f5f0d9ad1dbaea59e6fc7c0d8dcff864` | `run_pair_2x.py` |
| H2 per-session + call-count | `<2X>/state_H2.json` | 5363 | `1769c3bbcb62e952979e3a821afc47eebc1010c823c63f0fb825df42921d1299` | `run_pair_2x.py` |
| I2 per-session + call-count | `<2X>/state_I2.json` | 5361 | `0211c4dfd03c53f03036139042baf4dffa747c233c8c40758454ae71400f15b9` | `run_pair_2x.py` |
| H2↔I2 symdiff, prefix, retrieval, amplification | `<2X>/analysis_H2I2.json` | 2901 | `f69a0d549f5d01d6f3cba625ac869d50190efe933a2c1f7ea174f229d222b6ff` | `analyze_hi_2x.py` |

Reproduce: `python mem-audit/symdiff_probe.py --a dump_H2_p8.json --b dump_I2_p8.json --json-out out.json`
(dump-level); `python mem-audit/analyze_hi_2x.py` for the full analysis.
