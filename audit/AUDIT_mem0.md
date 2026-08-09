# Mem0 consistency audit — findings and measurements

A reproducibility and consistency audit of [Mem0](https://github.com/mem0ai/mem0),
run as an external observer through Mem0's own SDK. It reports four findings: three
engineering defects that caused silent memory loss, and one measured property of LLM
extraction (run-to-run divergence) that is not a defect. Every number cites the file
it comes from; a hash manifest (§7) lets a third party check the raw data was not
changed after publication.

> **Version scope (read first).** All measurements were taken on **mem0ai 1.0.11**.
> The current release is **2.0.17**, which **refactored away all three defects**
> (§3.0): §3.1 and §3.3 are gone because the O(store) update-decision call was
> replaced by a single-call additive extraction, and §3.2 is fixed by re-raising
> instead of the old silent `return []`. So this is a record of how the system
> behaved **before** that refactor — with numbers no one else has — not a report of
> a current bug. Independently, the three defects match the maintainers' own fix
> (their commit comment names the same 429-vs-no-facts confusion measured in §3.2).
> Finding **§3.4** (extraction non-determinism at temperature 0) is a property of the
> LLM, not of Mem0's code, so it is version-independent; §3.0 notes its status on
> 2.0.17.

This document is self-contained. The per-stage records it summarizes
(`RESULTS_mem0_symdiff.md`, `RESULTS_mem0_maxtokens.md`, `RESULTS_mem0_retrieval.md`,
`FINDINGS_silent_loss.md`, and the `PREREG_*.md` files) remain in this directory as
the primary records and are not rewritten.

---

## 1. What was measured, and why

The method is a falsification-first protocol: for each claim, register a prediction
before the run, keep the raw output, use controls, and state what a third party
would need to confirm it without trusting the authors. Here it is applied to an
**external** system through three checks: a repeat-run comparison, noise
decomposition, and pre-registration.

Mem0 is a widely used open-source memory layer for LLM applications: it extracts
"facts" from a conversation and stores them for later retrieval. Its extraction
accumulates facts and, by design, does not resolve contradictions — contradictory
facts are stored as separate ADD events rather than reconciled
([mem0ai/mem0#4896](https://github.com/mem0ai/mem0/issues/4896), "ADD-only
architecture doesn't implement conflict resolution…", closed as not planned). That
makes "does the same conversation yield the same memory twice?" a well-posed
question.

## 2. Configuration

| component | value |
|---|---|
| mem0ai | 1.0.11 |
| LLM (extraction + update decision) | Cerebras `gpt-oss-120b` via litellm, `temperature=0` |
| embedder | `sentence-transformers/all-MiniLM-L6-v2` (local; also the metric's embedder) |
| vector store | Chroma, local persistent |
| chromadb / sentence-transformers / numpy / python | 1.5.9 / 5.5.1 / 2.4.6 / 3.12.10 |
| `max_tokens` | 2000 (default runs A/B/C); 16000 (run F); 6000 (runs H/I) |
| request pacing | 12 s (A/B/C, F); 15 s (H/I) — outside the measured system (see §5) |

Material: person `p8` from the ES-MemEval `evo_emo.json` dataset — a 33-session
support dialogue. The dialogue text is withheld (ES-MemEval evaluation data); only
the identifier `p8` and derived counts are published. Fact dumps are kept out of the
repository; their paths, sizes and SHA-256 are in §7.

The consistency metric is `symdiff_probe.py` (unchanged across all comparisons):
greedy one-to-one matching of two string lists by descending cosine, reported at
`exact` (byte-identical) and cosine thresholds 0.60 / 0.72 / 0.82, as
symmetric-difference % of the union and Jaccard.

## 3. Findings

### 3.0 Status in the current release (2.0.17)

The findings below were measured on mem0ai 1.0.11. Verified against the current
`mem0/memory/main.py` on the default branch (mem0ai 2.0.17):

- **§3.1 and §3.3 no longer apply.** 2.x replaced the two-call add pipeline with a
  **single-call additive extraction** ("Phase 2: LLM extraction (single call)",
  system prompt `ADDITIVE_EXTRACTION_PROMPT`). There is no update-decision call that
  returns the whole memory list, so the output is no longer O(store): it does not
  grow with the store, does not truncate against `max_tokens` at a few dozen facts,
  and there is nothing whose `max_tokens` reservation the §3.3 loop could inflate.
- **§3.2 is fixed.** The extraction call's failure is now **re-raised** instead of
  swallowed. The code and its comment name exactly the confusion measured in §3.2:
  ```python
  except Exception as e:
      # Re-raise so callers can implement provider fallback / retry.
      # The original silent ``return []`` made upstream callers unable to
      # distinguish "LLM unavailable" (429/5xx/timeout) from "LLM
      # extracted no facts" -- both surfaced as an empty list.
      logger.error(f"LLM extraction failed: {e}")
      raise LLMError(f"LLM extraction failed: {e}") from e
  ```
  (A JSON-*parse* failure on a genuinely malformed response still sets an empty list
  quietly, but that is the model-output-quality case tracked in mem0ai#4540, not the
  O(store) truncation of §3.1.)
- **§3.4 is version-independent and now measured on 2.0.17** (`RESULTS_mem0_HI_2x.md`).
  It concerns the LLM's run-to-run extraction, not Mem0's control flow. Two clean
  single-call runs at `temperature=0` on 2.0.17 agree byte-for-byte on ~9 % of facts
  (Jaccard 0.22 at cosine 0.72), with 0/20 questions returning an identical top-5.
  **The refactor did not make extraction reproducible** — it is not in the
  architecture. (Direction vs 1.0.11 is not compared; see the RESULTS limitations.)

So §3.1–§3.3 are a record of pre-refactor behavior (with numbers), not current bugs.

### 3.1 Truncation of the growing update payload (defect; no longer applies in 2.x — §3.0)

Mem0's update-decision step returns the **entire accumulated memory list every
turn** (each stored fact plus an ADD/UPDATE/DELETE/NONE event). Output length
therefore grows linearly with the store — measured at **≈ 1566 + 55·n characters**
for a store of `n` facts (≈ 14 tokens/fact; `RESULTS_mem0_maxtokens.md` §3, from run
F's per-call instrumentation).

When that output exceeds `max_tokens`, the JSON is cut mid-structure; mem0 logs
`Invalid JSON response`, discards the turn's actions, and **the turn's facts are not
stored.** The store size at which this begins:

> **n★ ≈ (max_tokens − R − 392) / 14**,  R = the model's reasoning overhead
> (measured ≈ 900–1300 tokens, and variable turn to turn).

- default `max_tokens=2000` → **n★ ≈ 25–45 facts**
- `max_tokens=16000` → **n★ ≈ ~1000 facts**

Cross-check on run A (default config): first truncation at store **26** facts,
intermittent through store **49** — inside the predicted band. The intermittency is
mechanistic, not noise: near the budget the outcome flips with the turn's variable
reasoning length `R`. On the default configuration this dropped facts on **22 of 33
sessions in run A and 20 of 33 in run B** (`run_log`, §7).

This defect leaves a trace (the parse-error log).

### 3.2 Swallowed 429 on the update call (defect; fixed in 2.x — §3.0)

When the update-decision call returns HTTP 429 (rate limit), mem0 **catches it
internally** (`logger.error("Error in new memory actions response: …")`), sets the
response empty, and `add()` **returns success.** The caller is told the memory was
stored; the reconciliation never ran and nothing was stored. Unlike §3.1 there is no
parse error — the failure comes from the network and leaves only a log line the
application does not see.

This was found not by bug-hunting but by an invariant imposed for a different
reason — "never checkpoint a partially-processed session," added so a resumable run
would equal a continuous one. Enforcing it required checking, per session, whether
the write fully happened; the answer exposed this path. The tell is a session that
logs as successful with **one** LLM call recorded instead of two. Observed live
during run I (session s8: `DEGRADED (UPDATE-429)`, then re-run cleanly).

The mechanism is structural — it lives in mem0's control flow (a caught exception
on the update call, not the model's or the endpoint's behavior) — and was observed
here on Cerebras. A deployment that hits a 429 during the update call would lose
that write with no error to the caller. (`FINDINGS_silent_loss.md`.)

### 3.3 Quota reservation makes the §3.1 fix cause §3.2 (closed loop; moot in 2.x — §3.0)

Cerebras (and OpenAI-compatible endpoints generally) **reserve quota by
`max_completion_tokens`, not by actual output.** A 33-session ingest at
`max_tokens=16000` reserves 33·2·16000 ≈ **1.05 M tokens** — the entire daily
free-tier budget — while generating only ~140 k. Raising `max_tokens` to remove the
§3.1 truncation therefore exhausts the daily budget far faster and provokes the
429s of §3.2 (observed error: `Tokens per day limit exceeded`). The natural fix for
the first defect triggers the second. Each link is measured, not inferred.

### 3.4 Residual extraction divergence on a clean pair (a property, not a defect)

With truncation removed and no swallowed 429 (runs H and I, `max_tokens=6000`, both
33/33 sessions complete, every session verified to have made both LLM calls), two
runs of the identical configuration at `temperature=0` still produce **different
memory**: similar volume (189 vs 179 facts, 5.3 % apart) but **~⅓ different content**
(§4). This is not attributable to any of the defects above; it is a property of
LLM extraction at these settings. A 35 % run-to-run difference at `temperature=0` is
reported as an observation, not a bug.

**Confirmed on the current release (2.0.17), and this is the audit's strongest
result** (`RESULTS_mem0_HI_2x.md`). Two clean single-call runs (H2, I2; 33/33; every
session exactly one LLM call; `get_all` truncation-guarded) agree byte-for-byte on
only **~9 %** of facts, ~22 % at cosine 0.72 (Jaccard 0.22), with volume stable
(65 vs 68 facts) and **0 of 20** questions returning an identical top-5. The
refactor that removed §3.1–§3.3 did **not** make extraction reproducible —
reproducibility is not in the architecture, it is in the stochastic LLM extraction.

The **prefix curve** is the substantive part: symdiff (0.72) over sessions 0–k is
**0.0 % (0–4) → 26 → 63 → 74 → 78 % (0–32)**. On a short conversation the two runs
are byte-identical; divergence appears with accumulated context and grows with it,
with no plateau. Empirically, a memory layer built on LLM extraction is reliable on
short exchanges and increasingly unreliable across a long, multi-session history.

Bounds on the claim (see the RESULTS limitations): 65 facts is a small base, so the
percentage is volatile; the 1.0.11→2.0.17 *direction* is not compared (several
things changed at once); and the curve-shape contrast with 1.0.11 (which plateaued
near 35 %) is noted only as an observation that **needs a larger n**.

## 4. Numbers

**A/B/C and H/I answer different questions and are not two versions of one run.**
A/B/C are the **default configuration** (`max_tokens=2000`) — what a user gets out of
the box. H/I are the **post-fix** configuration (`max_tokens=6000`) — what remains
once the §3.1/§3.2 defects are removed.

### 4.1 Default configuration — runs A, B (`RESULTS_mem0_symdiff.md`)

Ingest: A = 57 facts (22/33 sessions truncated); B = 45 facts (20/33); 0 transport
errors (truncation, not 429, on this run).

| A↔B, default | exact | 0.60 | 0.72 | 0.82 |
|---|---|---|---|---|
| full symdiff % | 75.61 | 64.00 | 70.89 | 75.61 |
| cleaned (5 sessions parsed in both) % | 17.39 | 17.39 | 17.39 | 17.39 |

On the five sessions that parsed in both runs — three of which produced any facts —
extraction was **byte-identical** on those sessions (cleaned symdiff equal at every
threshold, Jaccard 0.83); the small residual is store contamination from the dropped
sessions. So the 64–76 % full number is dominated by
truncation loss, not by extraction divergence — at default settings the instability
a user sees is mostly §3.1.

Controls: **A↔A = 0.00 %** at every threshold (positive); **A↔C = 98.98–100 %**
(negative — C is a different dialogue, `p2`), confirming the metric separates
unrelated corpora and that MiniLM's full-sentence baseline does not inflate overlap.

Retrieval (20 fixed ES-MemEval `p8` questions, `search(top-5)`, zero LLM):
retrieval symdiff **73.8–82.2 %** ≥ the dump symdiff (64–75.6 %); 0/20 questions
returned an identical top-5. Amplification: diverging retrieved facts mean cosine to
the question **0.415** vs matched **0.470** — diverging facts are nearly as relevant,
so the loss reaches the user as different-but-relevant answers, not tail noise.
(`RESULTS_mem0_retrieval.md`; coverage-contamination caveat there.)

### 4.2 Post-fix configuration — runs H, I (`analysis_HI.json`)

Both complete all 33 sessions, 0 truncation, 0 swallowed 429. |H| = 189, |I| = 179
facts (volume divergence **5.3 %**).

| H↔I | exact | 0.60 | 0.72 | 0.82 |
|---|---|---|---|---|
| symdiff % | 54.55 | 28.04 | 34.98 | 41.38 |
| Jaccard | 0.45 | 0.72 | 0.65 | 0.59 |

Positive control **H↔H = 0.00 %** at every threshold.

Prefix curve (symdiff at 0.72 over sessions 0–k), showing where the divergence
accumulates:

| prefix | 0–4 | 0–9 | 0–16 | 0–24 | 0–32 |
|---|---|---|---|---|---|
| symdiff % (0.72) | 23.3 | 29.6 | 33.3 | 38.2 | 35.0 |

Interpretation: divergence rises with store depth (more turns, more update decisions,
each a chance to diverge) and plateaus near ~35 % — it accumulates but does not run
away.

Retrieval (same 20 questions): symdiff **42.2–60.8 %**, per-question Jaccard 0.336,
**1/20** identical top-5 — again ≥ the dump symdiff, so retrieval does not smooth the
divergence. Amplification: diverging facts cosine **0.484** vs matched **0.502**
(Δ +0.018) — diverging facts are as relevant as matched, i.e. the composition
difference is in on-topic content.

Reading: at default settings the visible instability is mostly truncation loss
(§3.1); once that is removed, a residual ~35 % (cosine 0.72) run-to-run composition
difference remains, with stable volume, and it reaches retrieval. That residual is
§3.4 — extraction non-determinism, not a defect.

### 4.3 F vs H (context; cause unestablished)

Run F (`max_tokens=16000`) produced 134 facts vs H's 189 — a ~40 % volume gap. Of
the 55-fact gap, ~11 are F's two tail sessions (extraction-429, 0 facts) and ~44 are
spread across sessions both ran cleanly. F was verified **not** silently degraded
(its call_log shows both LLM calls on every session 0–30; no swallowed 429). The
cause of the F/H gap is **not established**: `max_tokens` is the only known
difference, but F and H also differ in launch time, provider-queue state, and two
tail sessions, and no second 16000 run exists to isolate the cap. H and I (both 6000)
agree in volume to 5.3 %, so the typical volume is ~180; F at 134 is a low outlier of
unestablished cause.

## 5. Limitations

- **n = 1 dialogue** (`p8`), **one model** (`gpt-oss-120b`), **one provider**
  (Cerebras). The numbers are not claimed to generalize across dialogues, models, or
  providers. **§3.1 and §3.2 are structural** (in mem0's control flow, independent of
  model and provider). **§3.3 is provider-dependent**: reserving quota by
  `max_completion_tokens` rather than by actual output is a property of the endpoint's
  accounting policy — it was observed on Cerebras and need not hold on providers that
  meter by real usage. §3.4 is a single-configuration measurement.
- **F/H cause unestablished** (§4.3). `max_tokens` is a known but not a proven cause.
- **Cosine thresholds are not comparable across systems.** Mem0 facts are full
  sentences; short-label extractors (e.g. TBG in a prior project) sit on a different
  cosine scale — the negative control A↔C scoring ~99 % even at 0.60 shows full
  sentences barely move off exact. Only the `exact` column is comparable across
  systems.
- **Resumable vs continuous run.** H and I were ingested across hourly budget windows
  (hours elapse between some sessions) rather than continuously. Mem0 keeps all state
  in Chroma and its update-decision prompt contains no wall-clock time, so
  inter-session latency cannot change the result; the runs are equivalent to
  continuous ones on this point. The resumable engine additionally refuses to
  checkpoint any session that did not make both LLM calls, so completeness here is
  stricter than "33 sessions ran."
- **Protocol steps 3–6 not performed.** A full end-to-end evaluation (questions →
  answerer model → LLM judge over Mem0) was not run: it needs a large call volume the
  free tier's daily budget does not allow (§3.3). The zero-quota retrieval test (§4)
  is the product-level proxy done in its place — it shows whether the storage
  divergence reaches what `search()` returns, without an answerer or judge.

## 6. Predictions vs facts (PREREG)

Registered before each run; not edited. Misses kept.

| prediction (file) | predicted | actual | verdict |
|---|---|---|---|
| JSON failures/run, default (`PREREG_mem0_symdiff`) | 1–10 | 20–22 | **miss (far high)** — these are truncation, not "bad JSON"; the miss led to §3.1 |
| dump volumes, default | 80–170 | 57, 45 | miss (low) — truncation suppressed volume |
| A↔B cleaned symdiff | 30–80 % | 17.4 % | miss (low) — extraction identical on clean sessions |
| A↔C negative @0.60 | 80–95 % | 98.98 % | ~ (above) |
| 0 JSON failures under **constrained decoding** (`PREREG_mem0_constrained`) | 0 | many | **falsified** — grammar constraint does not stop truncation; falsification revealed §3.1's true cause |
| 0 truncations at 16000 (`PREREG_mem0_maxtokens`) | 0 | 0 (run F) | hit |
| F↔G symdiff | 8–25 % | untestable | G never completed (budget); recorded untestable |
| retrieval < dump, "cosmetic" (`PREREG_mem0_retrieval`) | retrieval ≈ 40–70 % of dump | retrieval ≥ dump | **refuted** on the A↔B proxy |
| H↔I volume divergence (`PREREG_HI`) | < 15 % | 5.3 % | **hit** |
| H↔I exact symdiff (`PREREG_HI`) | 25–50 % | 54.55 % | miss (just above) |

## 7. Manifest (number → file → SHA-256 → command)

Raw data files are outside the repository (withheld-dataset derivatives). SHA-256
computed once at run completion; files unchanged since. Code files
(`symdiff_probe.py`, `compare_dumps.py`, `mem0_resume.py`, `analyze_hi.py`, `window_once.py`,
`retrieval_questions.json`, …) are committed in this directory; git guarantees their
integrity.

Full SHA-256 (64 hex). `<DUMPS>`, `<MAXTOKENS>`, `<RESUME>`, `<2X>` are local
output directories used by the runs (outside the repository; substitute your own).
Only the file name and SHA-256 matter for verification — the directory is incidental.

| numbers | file | size (B) | SHA-256 | produced by |
|---|---|---|---|---|
| A ingest, A↔B (default) | `<DUMPS>/dump_A_p8.json` | 6023 | `ba47c74605a8963470ea193e99d408d11f859f0db10024fe8622d17ead105e1b` | `run_ingests.py` |
| B ingest, A↔B (default) | `<DUMPS>/dump_B_p8.json` | 4716 | `dbd3078f30dcf764629fe800a09b14d953c258ec53d1ee093e31454978833aac` | `run_ingests.py` |
| C (negative control) | `<DUMPS>/dump_C_p2.json` | 4266 | `0309f720aae09b13b2c2ea1ee9da7affa23c6b179b9004f00e412507b928ad21` | `run_ingests.py` |
| default failures/volumes | `<DUMPS>/run_log.json` | 2800 | `4c8b0a83799a1564ddd79245907c3636c75311bbd96ddfe1d7c7e77f76f2d871` | `run_ingests.py` |
| F facts (16000) | `<MAXTOKENS>/dump_F_p8.json` | 13925 | `500222f2fbe788d80dbfccdea41c898378f4d3b1cdd08eb06a2a7fd2c071c774` | `run_ingests_maxtokens.py` |
| ceiling curve, F call_log | `<MAXTOKENS>/run_log.json` | 21097 | `f7233a6d6e679874c598cb79c4fe54ddab405159847f4c254489e704fea4e588` | `run_ingests_maxtokens.py` |
| H facts (6000) | `<RESUME>/dump_H_p8.json` | 19590 | `b865e6af187dac97f1d6112a89393e310e4e13e593f06aaebf6b607a16bbdc3e` | `window_once.py` (mem0_resume) |
| I facts (6000) | `<RESUME>/dump_I_p8.json` | 18282 | `86c7bf2f7c84ee6295f67a17236d9990218a330e76aca83470fd0226721515ad` | `window_once.py` (mem0_resume) |
| H per-session instrumentation | `<RESUME>/state_H.json` | 8105 | `7924e99c8688a83ff1fc83a64ad85349f094977fc129b680b04e87ea303dad8c` | `window_once.py` |
| I per-session instrumentation | `<RESUME>/state_I.json` | 8105 | `9f624dcfa2d8afd22f05b2ea3b266eb3630f1bd006bdc12ef5dcbf671697632d` | `window_once.py` |
| H↔I symdiff, prefix, retrieval, amplification | `<RESUME>/analysis_HI.json` | 2932 | `1bec9e4e1c09f912fe52fba38adbe3e1c01f51e93677dbc645778017791474dd` | `analyze_hi.py` |
| H2 facts (2.0.17) | `<2X>/dump_H2_p8.json` | 11123 | `4282711266d1d33c6de55d4127ff40555b991fe2d3cab676640cb39a423ca4c5` | `run_pair_2x.py` (mem0_resume_2x) |
| I2 facts (2.0.17) | `<2X>/dump_I2_p8.json` | 12092 | `697f92f2b4ba9e3046a403da00cf2494f5f0d9ad1dbaea59e6fc7c0d8dcff864` | `run_pair_2x.py` |
| H2 per-session + call-count (2.0.17) | `<2X>/state_H2.json` | 5363 | `1769c3bbcb62e952979e3a821afc47eebc1010c823c63f0fb825df42921d1299` | `run_pair_2x.py` |
| I2 per-session + call-count (2.0.17) | `<2X>/state_I2.json` | 5361 | `0211c4dfd03c53f03036139042baf4dffa747c233c8c40758454ae71400f15b9` | `run_pair_2x.py` |
| H2↔I2 symdiff, prefix, retrieval, amplification (2.0.17) | `<2X>/analysis_H2I2.json` | 2901 | `f69a0d549f5d01d6f3cba625ac869d50190efe933a2c1f7ea174f229d222b6ff` | `analyze_hi_2x.py` |
| 20 questions (frozen) | `audit/retrieval_questions.json` (in repo) | 1303 | `4daba3365a270926e3ee13a2084b78755c54081af89c6de9988bff197986067d` | fixed before runs |
| the metric itself (unchanged in every comparison) | `audit/symdiff_probe.py` (in repo) | 5342 | `29c1b617486789c5ca69547483dba8420d5a9dae5434c3d82decf66ff8b5ccec` | — |
| dump-object adapter | `audit/compare_dumps.py` (in repo) | 1612 | `3ab6b948c331a86c7016169c3e9f9b08b0195bcb3edbe7388e314ff0ec8017a7` | — |

All SHA-256 above verify with `sha256sum <file>`. One caveat on the questions
file: `PREREG_mem0_retrieval.md` registered `5e51de93…`, which is the hash of the
*question list content* (`sha256(json.dumps(list))`), not of the file bytes — it
proves the 20 questions were fixed before the run; the file-bytes hash above is
`4daba336…`. Both are correct; they attest different things.

`audit/compare_dumps.py` extracts fact texts from the object-shaped dumps before
calling the unchanged metric. Reproduce a comparison, e.g. H↔I:
`python audit/compare_dumps.py <RESUME>/dump_H_p8.json <RESUME>/dump_I_p8.json`
Full H↔I analysis (symdiff + prefix + retrieval + amplification):
`python audit/analyze_hi.py`.

---

*Tone note: §3.1–§3.3 are reproducible defects and are named as such. §3.4 is a
measured property of LLM extraction at `temperature=0`, not a defect. Nothing here is
an accusation; it is a set of measurements a third party can repeat.*
