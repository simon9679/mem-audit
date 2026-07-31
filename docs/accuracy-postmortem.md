# Accuracy postmortem: what shifted, what held, and what we couldn't check

This is a factual account of how mem-audit's accuracy numbers were measured, how
they moved between measurements, and which questions turned out to be
unanswerable. It exists because an early version of the tool reported accuracy
without recording how those numbers were produced — and that omission is the
whole story.

Ground rule for this document: **no number appears here that isn't backed by an
artifact in the repository, the output of a committed script, or a commit** —
and where a number was *not* saved, that is stated plainly rather than papered
over. The test set throughout is the same 24-fact synthetic store with a known
ground truth (7 planted pairs — 3 duplicate, 2 contradiction, 2 update — plus
one topically-related "trap" pair and 8 noise facts), seeded by
`dev-scripts/confidence_test_seed.py`.

## The original claim

The first accuracy claim: **7/7 planted pairs caught, 0 false positives**, one
run. It was added to the README in commit `50981a1` ("add measured accuracy
results to README; add confidence-test scripts"), which is the artifact for this
claim. The run's actual report was **not retained** — only the summary sentence
in that commit survives.

## The repeat runs

Re-running the same store later produced **10 findings, not 7**. Recall was
unchanged (7/7), but there were now three findings that did not correspond to any
planted pair (false positives), and the two pairs planted as UPDATE came back
typed CONTRADICTION. Two consecutive repeat runs agreed with each other exactly —
same candidate-pair count and a finding-by-finding match on memory ids.

These repeat-run reports were also **not retained**. The outcome is preserved as
a fixture rather than a saved report: `tests/test_confidence_analysis.py`
reconstructs it exactly (7 planted pairs, 10 findings, 7 landing on a planted
pair) and asserts the score — recall 7/7, precision 7/10, 5 correct type, 2 wrong
type, 3 false positives. The candidate-pair count reported at the time (76) came
from the runs themselves and has no saved artifact; it is recorded here as
reported, not as independently verifiable.

## Hypotheses, and how each was closed

- **Changes in our own code.** The judge prompt (`_JUDGE_PROMPT`), the sampling
  temperature (`temperature=0.0`), the model name, and the candidate-selection
  code (`top_k_neighbor_pairs`) are unchanged across the states in question — see
  `mem_audit/detectors/contradictions.py`, `mem_audit/detectors/duplicates.py`,
  and the git history of those files. The id tiebreaker in `judge_pair` cannot be
  the cause either: it only runs when a `created_at` is missing or two are equal,
  and the 24 seeded facts each carry a distinct `created_at`.
- **Reused database state.** Ruled out by construction: fresh clone, fresh store,
  24 records scanned, 24 distinct timestamps. (The 24-distinct-timestamp property
  was observed in the runs; the seed inserts 24 facts, one per entry in
  `confidence_test_seed.py`.)
- **A changed model catalog.** The judge default `gpt-oss-120b` was present and
  remained the default — see the `cerebras` preset in `mem_audit/providers.py`.
- **In-session model nondeterminism.** Ruled out: the two consecutive repeat runs
  produced an identical result — same candidate count, a full id-level match on
  findings. With `temperature=0.0` and two identical runs, sampling noise is not
  the explanation.
- **Embedding drift / a moved top-k boundary.** The two repeat runs surfaced the
  same set of candidate pairs, so the cheap pass was stable between them.

## What remained, and why it can't be checked

One hypothesis survives: a silent change to the model or the embedder — same
name, different behavior — between measurements separated by time. There is
**nothing to check it against.** The early reports recorded no model version, no
parameters, no provider identity. The cause of the shift between the first and
later measurements **is not established, and cannot be established.** That is the
honest end of that thread.

## An unplanned end to the question

On **July 30, 2026, GitHub Models was fully retired** — playground, model
catalog, inference API, and bring-your-own-key endpoints, for all customers
including active ones ([GitHub Changelog, 2026-07-01][gh]). All three historical
measurements above used GitHub Models `text-embedding-3-small` embeddings. They
can no longer be reproduced at all: it is not a matter of a model version — the
entire provider is gone. (A live check on the retirement date returned
`HTTP 410 github_models_retirement_brownout` from the endpoint.)

## A fourth measurement, on a different stack

The current measurement uses a completely different embedder: local Ollama
`nomic-embed-text` (768 dimensions) in place of the cloud
`text-embedding-3-small` (1536), same Cerebras `gpt-oss-120b` judge. Result:
**recall 7/7, precision 7/8, 85 candidate pairs, 5 findings with the correct type
and 2 with the wrong type (both update pairs typed CONTRADICTION), 1 false
positive.** These numbers are recorded in the README "Measured accuracy" section
and were produced by the run described in PR #12; the configuration is
reproducible today from committed files (`dev-scripts/write_confidence_config.py`
+ `confidence_test_seed.py`, then `--embed-provider ollama --llm-provider
cerebras`), scored by `dev-scripts/analyze_confidence_test.py`. The raw report is
not committed (confidence-test outputs are gitignored), but — unlike the early
runs — it can be regenerated.

## What this separates out — the actual result

Comparing two radically different embedders splits the observations into the
stable and the variable:

- **Recall held at 7/7 on both** — robust to the embedder.
- **Both update pairs were typed CONTRADICTION under both configurations** — a
  reproducible property of the judge, not noise.
- **The false-positive count moved (3 → 1)** — it tracks which pairs the
  embedding pass surfaces, i.e. candidate selection, not the judge.

This is worth more than any single accuracy figure. It is **not** evidence that
one embedder is more accurate than the other: one measurement per configuration
and a two-finding difference does not support that claim, and none is made.

## What was changed in response

- `--json-out` reports now carry a `metadata` block — tool version, provider and
  the **actual** model names, all parameters, candidate-pair count, and the
  judge's verdict distribution (PR #10, `mem_audit/report.py`,
  `mem_audit/cli.py`).
- Scoring is mechanical, by memory id, not by reading paraphrased summaries
  (`dev-scripts/analyze_confidence_test.py`), and the computation is held in place
  by a test (`tests/test_confidence_analysis.py`).

## The general point

For a tool whose decisions come from a language model, **reproducibility within a
day says nothing about reproducibility a month later unless the version of the
entire stack is recorded with the result.** And the thing that fails need not be
the model: an entire provider can disappear. Here, one did.

## Where this procedure comes from

The moves in this postmortem — re-run the same store, check whether the numbers
reproduce, and separate what holds from what floats — are not ad hoc. They are
steps of a falsification protocol written up separately in
[`simon9679/tbg-postmortem`](https://github.com/simon9679/tbg-postmortem): a
cheap-to-expensive procedure for deciding whether a memory system's advantage
deserves trust before an expensive comparison. That protocol came out of a
different project — a belief-memory engine — and mem-audit is a system it was
**not** designed for. Its step 2, reproducibility (re-ingest), nonetheless did
exactly what it is meant to do here: the original "7/7 planted pairs, 0 false
positives" claim did not survive a repeat run, which surfaced three false
positives the single run had hidden. A claim that fails re-ingest was never a
measurement — which is the whole reason the step exists.

[gh]: https://github.blog/changelog/2026-07-01-github-models-is-being-fully-retired-on-july-30-2026/
