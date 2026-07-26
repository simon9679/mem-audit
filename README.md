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
(`get_all`), reports what it finds, and stops. You decide what to fix and how.
(Staleness here means "a newer memory likely supersedes an older one," judged
from the two facts themselves — not from Mem0's per-memory `history`.)

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
- Does not paginate a self-hosted `mem0.Memory`. That client's `get_all()` has
  no cursor, so mem-audit fetches up to `--page-size` records (default 500) and
  **aborts rather than silently auditing a partial store** if it gets back
  exactly that many — it can't tell a full store from a truncated page. The
  practical ceiling for one run on self-hosted `Memory` is therefore
  `page_size - 1`; raise `--page-size` once you know roughly how many memories
  the user has. (The hosted `MemoryClient` paginates normally.)
- Does not attempt persona-drift detection for coding agents — for that,
  see [Nautilus Compass](https://github.com/chunxiaoxx/nautilus-compass),
  which solves a related but different problem for coding-agent sessions.

## Install

```bash
pip install -e .
```

Embedding batches are sized by a cheap `len/4` token estimate by default. For
exact token counts (via `tiktoken`), install the optional extra — it's not
required, and CI/offline runs work without it:

```bash
pip install -e ".[precise]"
```

## Try it first — offline, no keys, no network

```bash
python examples/demo_offline.py
```

Runs the full pipeline against a synthetic memory store that reproduces the
`#4896` scenario, using fake embeddings and a canned LLM judge — no network
calls, no API keys. This is the fastest way to see what the tool does before
wiring up anything real.

## A real run needs two independent configurations

This trips up almost everyone on the first real run, so up front: **there are
two separate embedder/LLM setups, and they do not share flags.**

1. **mem0 has its own embedder and LLM.** When mem-audit creates the mem0
   client (`Memory()` or `Memory.from_config(...)`), mem0 brings up *its own*
   embedder and LLM from *its own* config. mem-audit's `--embed-provider` /
   `--llm-provider` flags **do not affect this at all.** With no config, mem0's
   default embedder needs `OPENAI_API_KEY`, and the run stops there if it's
   missing.
2. **mem-audit has its own embedder and judge.** These are what actually run
   the audit, and they're controlled by the flags described under
   "Choosing embedding and judge endpoints" below.

Point mem-audit at a mem0 config you can actually bring up, with `--config`.
You don't need an OpenAI account for this — mem0's `openai` provider is just an
OpenAI-*compatible* client, and `openai_base_url` decides where it actually
goes. Here it points mem0's own embedder and LLM at GitHub Models'
OpenAI-compatible endpoint (needs a `models: read` token). **No keys in the
file** — mem0 reads the key from the
`OPENAI_API_KEY` environment variable, so for this endpoint you set
`OPENAI_API_KEY` to your GitHub token:

```json
{
  "vector_store": {
    "provider": "qdrant",
    "config": { "path": "./mem0_qdrant_db", "collection_name": "mem_audit" }
  },
  "embedder": {
    "provider": "openai",
    "config": {
      "model": "openai/text-embedding-3-small",
      "openai_base_url": "https://models.github.ai/inference"
    }
  },
  "llm": {
    "provider": "openai",
    "config": {
      "model": "openai/gpt-4o-mini",
      "openai_base_url": "https://models.github.ai/inference"
    }
  }
}
```

> mem0 sends anonymous usage telemetry to PostHog on startup. On a network
> where that host is blocked, that surfaces as a wall of tracebacks around the
> report — harmless, but it looks like mem-audit broke. Set `MEM0_TELEMETRY=False`
> to turn it off.

If you *do* have an OpenAI account, the config is the same shape without the
`openai_base_url` lines (and `OPENAI_API_KEY` then holds a real OpenAI key):

```json
{
  "vector_store": {
    "provider": "qdrant",
    "config": { "path": "./mem0_qdrant_db", "collection_name": "mem_audit" }
  },
  "embedder": { "provider": "openai", "config": { "model": "text-embedding-3-small" } },
  "llm": { "provider": "openai", "config": { "model": "gpt-4o-mini" } }
}
```

## Choosing embedding and judge endpoints

mem-audit's own embedder and judge talk to any OpenAI-compatible endpoint.
Named presets are shortcuts for known endpoints — a base URL, which environment
variable holds the key, and default model ids:

| preset | role(s) | key env var | default model(s) |
| --- | --- | --- | --- |
| `openai` | embeddings + judge | `OPENAI_API_KEY` | `text-embedding-3-small` (embed), `gpt-4o-mini` (judge) |
| `github` | embeddings | `GITHUB_TOKEN` (needs `models: read`) | `openai/text-embedding-3-small` |
| `cerebras` | judge | `CEREBRAS_API_KEY` | `gpt-oss-120b` |

```bash
mem-audit run --user-id alice --config ./mem0_config.json \
  --embed-provider github --llm-provider cerebras
```

For any endpoint not in that table, generic flags take over. **An explicit flag
overrides the preset**, and an explicit `--embed-base-url` / `--llm-base-url`
**ignores the preset entirely and then requires an explicit model:**

- Embedder: `--embed-provider`, `--embed-base-url`, `--embed-model`, `--embed-api-key-env`
- Judge: `--llm-provider`, `--llm-base-url`, `--llm-model`, `--llm-api-key-env`

```bash
# fully custom OpenAI-compatible endpoints, no preset involved:
mem-audit run --user-id alice --config ./mem0_config.json \
  --embed-base-url https://my-host/v1 --embed-model my-embed-model --embed-api-key-env MY_KEY \
  --llm-base-url   https://my-host/v1 --llm-model   my-judge-model  --llm-api-key-env MY_KEY
```

Some endpoints limit how many requests you can make per minute rather than a
token budget; a preset carries a conservative `--min-request-interval` default
for those, which you can raise or lower (`0` disables the wait between judge
calls). A preset's default model can also disappear from your account over
time — if so, pass `--embed-model` / `--llm-model` with whatever the endpoint
currently offers.

Keys are read from environment variables, never passed as flags — see
[`.env.example`](.env.example):

```
OPENAI_API_KEY=      # openai preset (embeddings and/or judge)
GITHUB_TOKEN=        # github preset (embeddings); needs the 'models: read' permission
CEREBRAS_API_KEY=    # cerebras preset (judge)
```

## What a run costs you (in calls, not dollars)

Two passes, with very different call counts:

- **Embeddings** — one pass over every memory text, split into batches that fit
  the endpoint's per-request limit. Roughly one request per batch.
- **Judge** — one LLM call *per candidate pair*, and this is the volume driver.

The number of candidate pairs is bounded by `N × k / 2` after de-duplication,
where `N` is the number of memories and `k` is `--top-k` (default 5): each
memory contributes its `k` nearest neighbors, and each shared pair is counted
once. So a 200-memory store at the default `k=5` is **up to ~500 judge calls.**

`--top-k` sets that ceiling directly; `--min-request-interval` sets the pace
between calls. Lower either to make fewer, or slower, calls.

## Run it

```bash
mem-audit run --user-id alice --config ./mem0_config.json --json-out report.json
```

With no `--config`, mem-audit uses mem0's own default config / env vars for the
mem0 client (see "A real run needs two independent configurations" — mem0's
default embedder needs `OPENAI_API_KEY`).

> If `mem-audit` isn't found after install (common on Windows, where pip puts
> the console script in a `Scripts` directory that isn't always on your `PATH`),
> run the exact same CLI as a module instead:
>
> ```bash
> python -m mem_audit run --user-id alice --config ./mem0_config.json
> ```

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
   candidates doesn't look hung. The judge's date-aware prompt shows each
   memory's `created_at` (when known), since the time gap is what separates a
   genuine `CONTRADICTION` from an expected `UPDATE`. 429s are retried with
   backoff (`--max-retries`), calls can be throttled (`--min-request-interval`),
   and `--json-out` is flushed after every pair so an interrupted run still
   leaves a valid report.
4. `report.py` — prints a table sorted by severity, highest first (contradictions
   on top). `--json-out` for CI use.

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

Separately — and this is a **scale/plumbing check, not a second accuracy
benchmark** — the tool has been run end-to-end against a larger 161-fact store
on real GitHub Models embeddings (not mocks). Here 161 is the total store size,
not a count of labelled pairs. The point of that run was to confirm the batching
path holds real volume: the embedding pass split into multiple token-bounded
requests (and a single unbatched request over the same volume returns the real
`413 max-tokens-per-request` error), all 161 memories were read back with no
silent truncation, and the handful of pairs planted in that store were
classified correctly by a real Cerebras judge. Treat the 24-fact run above as
the accuracy measurement; treat this one as evidence the real embedding endpoint
survives a realistic volume.

## Related work

`mem-audit` is not the only project in this space. In rough order of how
close they are to what this does:

- [mem0ai/mem0#5850](https://github.com/mem0ai/mem0/issues/5850) — an
  open, in-progress proposal for built-in compaction inside Mem0 itself
  (a `max_memories` threshold with merge-first, evict-fallback consolidation).
  If/when this lands, it may cover part of what `mem-audit` catches — natively,
  write-time, and with automatic merging rather than a human-reviewed report.
- [mem0ai/mem0-lifecycle](https://github.com/HH1162/mem0-lifecycle) —
  a third-party plugin that decays unused memories over time
  (Ebbinghaus-curve based), a different axis (staleness-by-neglect) than
  duplicate/contradiction detection.
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

MIT — see [LICENSE](LICENSE).
