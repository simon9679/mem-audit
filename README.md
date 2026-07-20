# mem-audit

External consistency auditor for [Mem0](https://github.com/mem0ai/mem0)-based memory stores.

Mem0's current extraction pipeline is single-pass ADD-only: facts accumulate,
nothing is overwritten. This is an explicit, official design decision, not a
bug — see [mem0ai/mem0#4896](https://github.com/mem0ai/mem0/issues/4896)
(closed as "not planned"), where a Mem0 maintainer confirms: *"our v3 SDK
handles contradictions by design through the extraction prompt and memory
linking, not through an explicit UPDATE/conflict resolution code path...
Both memories being stored is intentional — the historical record has
value, and the retrieval layer is designed to prioritize the most relevant
(typically newest) memory."*

That's a reasonable design tradeoff. It also means contradictory and
duplicate facts are guaranteed to coexist in your store indefinitely, with
no built-in way to review them — `mem-audit` is that review step, external
to Mem0 by design, not a workaround for something they're about to fix.

`mem-audit` doesn't replace your memory store or migrate your data anywhere.
It connects to your existing Mem0 instance through the standard SDK
(`get_all`, `history`), reports what it finds, and stops. You decide what to
fix and how.

## What it catches

- **Duplicates** — near-identical facts stored twice (cheap embedding pass).
- **Contradictions** — facts that can't both be true right now (LLM-judge pass,
  only run on the candidates the cheap pass surfaces, to keep cost down).
- **Stale/superseded facts** — facts a newer memory has likely replaced,
  flagged for review rather than silently retired.

## What it does not do

- Does not modify, delete, or migrate anything in your memory store.
- Does not require switching vector store backends — works with whatever
  Mem0 is already configured to use (Qdrant, pgvector, Chroma, ...),
  because it talks to Mem0's client API, not the backend directly.
- Does not attempt persona-drift detection for coding agents — for that,
  see [Nautilus Compass](https://github.com/chunxiaoxx/nautilus-compass),
  which solves a related but different problem for coding-agent sessions.

## Install

```bash
pip install -e .
```

## Usage

```bash
mem-audit run --user-id alice
```

Uses your existing `mem0` config/env vars by default. To point at a specific
config:

```bash
mem-audit run --user-id alice --config ./mem0_config.json --json-out report.json
```

### Running without paid API keys

By default `mem-audit` uses OpenAI directly for both embeddings and the
LLM judge. If you don't have (or don't want to spend) an OpenAI budget,
two free-tier providers are wired in:

```bash
export GITHUB_TOKEN=...       # needs 'models: read' — https://github.com/settings/tokens
export CEREBRAS_API_KEY=...   # free, no card — https://cloud.cerebras.ai/

mem-audit run --user-id alice --embed-provider github --llm-provider cerebras
```

This split is deliberate: embeddings are one batched call per audit (cheap,
fits GitHub Models' tighter per-request quota), while the judge is called
once per candidate pair — the actual volume driver — which is why it's
routed to Cerebras' more generous 1M-tokens/day free tier instead.

Cerebras' free-model catalog has changed more than once in 2026 — if the
default (`gpt-oss-120b`) isn't in your account, pass `--llm-model <name>`
with whatever's currently available.

## Try it without any API keys

```bash
python examples/demo_offline.py
```

Runs the full pipeline against a synthetic memory store that reproduces the
`#4896` scenario, using fake embeddings and a canned LLM judge — no network
calls. Good for seeing the tool's behavior before wiring up real credentials.

## How it works

1. `Mem0Connector.fetch_all(user_id)` — reads every memory via the Mem0 SDK.
2. `find_duplicate_candidates` — cheap embedding pass finds each memory's
   top-k nearest neighbors (default k=5), not a fixed cosine cutoff.
   OpenAI-family embeddings aren't reliably calibrated for absolute
   similarity thresholds (confirmed against real text-embedding-3-small
   output, not just theory — see `mem_audit/embeddings.py` for specifics),
   so top-k sidesteps guessing a "correct" number. Pass
   `--similarity-threshold` to opt into the old fixed-cutoff behavior
   instead.
3. `find_contradictions` — an LLM judge classifies each candidate pair as
   `DUPLICATE` / `CONTRADICTION` / `UPDATE` / `UNRELATED`. Only the first
   pass's output feeds this step, so cost stays roughly linear in the number
   of *near* pairs, not O(n²) LLM calls. Judging is sequential (one call
   per pair) — a progress line prints to stderr so a run with dozens of
   candidates doesn't look hung.
4. `report.py` — prints a severity-sorted table. `--json-out` for CI use.

## Measured accuracy

Ran against a 24-fact synthetic memory store with known ground truth (7
deliberately-planted duplicate/contradiction/update pairs, paraphrased —
not template swaps — plus a topically-related-but-not-duplicate "trap"
pair and 8 unrelated facts as noise), through the real CLI with real
providers (GitHub Models embeddings + Cerebras judge, not mocks):

- **7/7 planted pairs caught** (3 duplicates, 2 contradictions, 2 updates)
- **0 false positives** — the trap pair and all 8 noise facts correctly
  produced no findings

This is one test on English, short-sentence, personal-memory-style facts —
not a claim it generalizes to every language, store size, or fact
structure. Take it as "the approach works as designed," not "guaranteed
accuracy on your data."

## Related work

`mem-audit` is not the only project in this space. In rough order of how
close they are to what this does:

- [mem0ai/mem0#5850](https://github.com/mem0ai/mem0/issues/5850) — an
  open, in-progress proposal for built-in compaction inside Mem0 itself
  (merge-first, evict-fallback). If/when this lands, it may cover part of
  what `mem-audit` catches — natively, write-time, and with automatic
  merging rather than a human-reviewed report.
- [mem0ai/mem0-lifecycle](https://github.com/HH1162/mem0-lifecycle) —
  a third-party plugin that decays unused memories over time
  (Ebbinghaus-curve based), a different axis (staleness-by-neglect) than
  duplicate/contradiction detection.
- A write-time "DedupMemory" wrapper shared in
  [mem0ai/mem0#5352](https://github.com/mem0ai/mem0/issues/5352#issuecomment)
  by a community member — intercepts at `add()` time rather than
  auditing after the fact.
- [TeleMem](https://github.com/TeleAI-UAGI/telemem) — a full drop-in
  replacement for Mem0 with built-in semantic deduplication, rather than
  an external tool you point at an existing store.

The distinction `mem-audit` is trying to hold onto: **read-only, external,
human-in-the-loop**. Everything above either modifies your store
automatically or requires migrating to it. If that distinction stops
mattering to you, any of the above may be a better fit than this.

## Status

Early / MVP. Level 1 (duplicates + contradictions) and staleness-via-UPDATE
are implemented. Persona-drift detection for companion/roleplay bots
(anchor-based, distinct from Nautilus Compass's coding-agent focus) is
planned as a follow-up once there's signal this is useful to more than one
person.

Feedback, especially "this doesn't match how my Mem0 store actually looks,"
is more useful right now than feature requests.

## License

MIT
