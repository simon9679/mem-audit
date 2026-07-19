# mem-audit

External consistency auditor for [Mem0](https://github.com/mem0ai/mem0)-based memory stores.

Mem0's current extraction pipeline is single-pass ADD-only: facts accumulate,
nothing is overwritten. That's a deliberate design choice, but it means
contradictory and duplicate facts pile up silently unless something else
catches them. See [mem0ai/mem0#4896](https://github.com/mem0ai/mem0/issues/4896)
and [#4536](https://github.com/mem0ai/mem0/issues/4536) for two concrete,
open examples.

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
2. `find_duplicate_candidates` — cheap cosine-similarity pass narrows N
   memories down to a small set of close pairs.
3. `find_contradictions` — an LLM judge classifies each candidate pair as
   `DUPLICATE` / `CONTRADICTION` / `UPDATE` / `UNRELATED`. Only the first
   pass's output feeds this step, so cost stays roughly linear in the number
   of *near* pairs, not O(n²) LLM calls.
4. `report.py` — prints a severity-sorted table. `--json-out` for CI use.

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
