from __future__ import annotations

import click

from mem_audit.pipeline import run_audit
from mem_audit.providers import (
    EMBED_PRESETS,
    JUDGE_PRESETS,
    PRESETS,
    resolve_embedder,
    resolve_judge,
)
from mem_audit.report import export_json, print_report


@click.group()
def main():
    """mem-audit: external consistency auditor for Mem0-based memory stores."""


@main.command()
@click.option("--user-id", required=True, help="Mem0 user_id to audit.")
@click.option("--config", type=click.Path(exists=True), default=None,
              help="Path to a Mem0 config JSON (vector_store, embedder, llm). "
                   "If omitted, uses Mem0's own default config / env vars.")
@click.option("--top-k", type=int, default=5, show_default=True,
              help="For each memory, how many nearest neighbors to send to the "
                   "LLM judge. The judge runs once per candidate pair, so this "
                   "directly controls how many judge calls a run makes. Default "
                   "candidate-selection strategy — see --similarity-threshold "
                   "for the old fixed-cutoff alternative.")
@click.option("--min-similarity", type=float, default=0.05, show_default=True,
              help="Loose floor for --top-k candidates — skips obviously-unrelated "
                   "pairs before spending an LLM call, not a duplicate/contradiction "
                   "decision boundary.")
@click.option("--similarity-threshold", type=float, default=None,
              help="Opt into the old fixed-cosine-cutoff strategy instead of --top-k "
                   "(e.g. 0.75-0.87 are common starting points, but there is no single "
                   "correct value for OpenAI-family embeddings — see README).")
@click.option("--page-size", type=int, default=500, show_default=True,
              help="Max memories to fetch per page. Self-hosted mem0.Memory has no "
                   "pagination cursor — if a user has more memories than this, the "
                   "audit aborts rather than silently reporting on a partial dataset.")
@click.option("--embed-provider", type=click.Choice(EMBED_PRESETS), default="openai",
              show_default=True,
              help="Named embedding-endpoint preset (base URL, key env var, model, "
                   "batch sizes; see mem_audit/providers.py). Embeddings run as a "
                   "single pass over the store in token-bounded batches. Override "
                   "individual fields with --embed-model / --embed-api-key-env, or "
                   "point at an endpoint not in this list with --embed-base-url.")
@click.option("--embed-base-url", default=None,
              help="Escape hatch: embed against any OpenAI-compatible endpoint not in "
                   "the preset list. Requires --embed-model. When set, the "
                   "--embed-provider preset is ignored entirely.")
@click.option("--embed-model", default=None,
              help="Embedding model id. Overrides the preset's model, or supplies the "
                   "required model when --embed-base-url is used.")
@click.option("--embed-api-key-env", default=None,
              help="Name of the environment variable holding the embedding endpoint's "
                   "API key. Overrides the preset's default env var.")
@click.option("--llm-provider", type=click.Choice(JUDGE_PRESETS), default="openai",
              show_default=True,
              help="Named judge-endpoint preset. The judge is called once per "
                   "candidate pair, so it is the volume-driving step in a run "
                   "(--top-k controls the count). For many endpoints the binding "
                   "constraint is requests-per-minute, not a token budget — see "
                   "--min-request-interval. Override with --llm-model / "
                   "--llm-api-key-env, or use --llm-base-url for an unlisted endpoint.")
@click.option("--llm-base-url", default=None,
              help="Escape hatch: judge against any OpenAI-compatible chat endpoint "
                   "not in the preset list. Requires --llm-model. When set, the "
                   "--llm-provider preset is ignored entirely.")
@click.option("--llm-api-key-env", default=None,
              help="Name of the environment variable holding the judge endpoint's "
                   "API key. Overrides the preset's default env var.")
@click.option("--llm-model", default=None,
              help="Override the judge model id. Also required when --llm-base-url "
                   "points at an unlisted endpoint. If a preset's default model isn't "
                   "available in your account, pass an explicit model (check the "
                   "endpoint's own model list).")
@click.option("--max-retries", type=int, default=5, show_default=True,
              help="How many times to retry a judge call that hits HTTP 429 "
                   "before giving up on that pair. Backoff honors a retry-after "
                   "header when present, else exponential (2/4/8/16/32s). A pair "
                   "that exhausts its retries is skipped, not fatal.")
@click.option("--min-request-interval", type=float, default=None,
              help="Seconds to sleep between judge calls, to stay under an endpoint's "
                   "requests-per-minute limit. Defaults to the chosen provider's "
                   "conservative preset value (0 for endpoints without a frequency "
                   "limit). An explicit value always wins.")
@click.option("--json-out", type=click.Path(), default=None,
              help="Also write findings to a JSON file. Written incrementally "
                   "(atomically, after each pair), so an interrupted run still "
                   "leaves a valid partial report.")
def run(user_id: str, config: str | None, top_k: int, min_similarity: float,
        similarity_threshold: float | None, page_size: int,
        embed_provider: str, embed_base_url: str | None, embed_model: str | None,
        embed_api_key_env: str | None,
        llm_provider: str, llm_base_url: str | None, llm_api_key_env: str | None,
        llm_model: str | None,
        max_retries: int, min_request_interval: float | None, json_out: str | None):
    """Audit a single user's memory store for duplicates, contradictions, and staleness."""
    from mem0 import Memory  # imported lazily so `mem-audit --help` doesn't require mem0ai extras

    def _init_client():
        if config:
            import json as _json

            with open(config, "r", encoding="utf-8") as fh:
                cfg = _json.load(fh)
            return Memory.from_config(cfg)
        return Memory()

    try:
        client = _init_client()
    except Exception as e:  # noqa: BLE001 — surface mem0's own init failure as a clean CLI error
        raise click.ClickException(
            "Failed to initialize the mem0 client. This happens inside mem0, "
            "before mem-audit does anything: mem0 builds its OWN embedder/LLM "
            "from its default configuration, and mem-audit's --embed-provider / "
            "--llm-provider flags do not affect that. The most common cause is a "
            "missing OPENAI_API_KEY for mem0's default embedder. Fix it by passing "
            "--config with a mem0 config JSON that uses a provider you have "
            f"credentials for. Underlying error: {e}"
        )

    # Build mem-audit's own embedder/judge clients. These constructors validate
    # credentials eagerly (missing key, escape-hatch base URL without a model,
    # or a provider that can't serve the requested role all raise ValueError),
    # so wrap them here to turn that into a clean ClickException.
    try:
        embed_fn = resolve_embedder(
            embed_provider,
            base_url=embed_base_url,
            model=embed_model,
            api_key_env=embed_api_key_env,
        )
        llm_call = resolve_judge(
            llm_provider,
            base_url=llm_base_url,
            model=llm_model,
            api_key_env=llm_api_key_env,
            max_retries=max_retries,
        )
    except ValueError as e:
        raise click.ClickException(str(e))

    # Default the inter-call throttle from the chosen judge preset (0 for the
    # escape-hatch path, which has no preset). An explicit value always wins.
    if min_request_interval is None:
        min_request_interval = 0.0 if llm_base_url else PRESETS[llm_provider].min_request_interval

    skipped_pairs = 0

    def on_skip(_pair) -> None:
        nonlocal skipped_pairs
        skipped_pairs += 1

    def on_stage(message: str) -> None:
        # Plain lines via click.echo, not \r-based — \r-overwrite progress
        # is unreliable across terminals (confirmed: invisible in at least
        # one real PowerShell session despite working correctly in
        # isolated testing). A guaranteed-visible line beats a fancier one
        # that might not render.
        click.echo(message, err=True)

    def on_progress(done: int, total_pairs: int) -> None:
        click.echo(f"  judged {done}/{total_pairs}", err=True)

    try:
        findings, total = run_audit(
            mem0_client=client,
            user_id=user_id,
            embed_fn=embed_fn,
            llm_call=llm_call,
            top_k=top_k,
            min_similarity=min_similarity,
            similarity_threshold=similarity_threshold,
            page_size=page_size,
            on_progress=on_progress,
            on_stage=on_stage,
            min_request_interval=min_request_interval,
            partial_out=json_out,
            on_skip=on_skip,
        )
    except RuntimeError as e:
        raise click.ClickException(str(e))
    except ValueError as e:
        # Data-shape problems surfaced mid-pipeline (e.g. embed_fn returned a
        # different number of vectors than inputs — see duplicates.py). Missing
        # credentials are already handled when the clients are built above.
        raise click.ClickException(str(e))

    print_report(findings, total_memories=total, user_id=user_id)

    if skipped_pairs:
        click.echo(
            f"\n{skipped_pairs} pair(s) skipped due to rate limits — re-run to "
            f"cover them, or raise --max-retries / --min-request-interval.",
            err=True,
        )

    if json_out:
        # run_audit already flushed findings to json_out incrementally after
        # every pair; this final write just guarantees the file exists even
        # when there were zero candidate pairs (nothing to flush).
        export_json(findings, json_out)
        click.echo(f"\nFindings written to {json_out}")


if __name__ == "__main__":
    main()
