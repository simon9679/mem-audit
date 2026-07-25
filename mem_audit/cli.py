from __future__ import annotations

import click

from mem_audit.embeddings import github_models_embedder, openai_embedder
from mem_audit.detectors.contradictions import cerebras_llm_judge, default_llm_judge
from mem_audit.pipeline import run_audit
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
                   "LLM judge. Default candidate-selection strategy — see "
                   "--similarity-threshold for the old fixed-cutoff alternative.")
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
@click.option("--embed-provider", type=click.Choice(["openai", "github"]), default="openai",
              show_default=True,
              help="'github' uses GitHub Models' free embeddings endpoint "
                   "(needs GITHUB_TOKEN with 'models: read'). Texts are embedded "
                   "in small token-bounded batches to fit its tight per-request quota.")
@click.option("--llm-provider", type=click.Choice(["openai", "cerebras"]), default="openai",
              show_default=True,
              help="'cerebras' uses Cerebras' free judge endpoint (needs "
                   "CEREBRAS_API_KEY). The judge is called once per "
                   "candidate pair, so it's the higher-volume step — a "
                   "generous free tier matters more here than for embeddings.")
@click.option("--llm-model", default=None,
              help="Override the judge model name. Required if --llm-provider=cerebras "
                   "and the default ('gpt-oss-120b') isn't in your account's current "
                   "model list — Cerebras' free catalog has changed more than once in 2026.")
@click.option("--max-retries", type=int, default=5, show_default=True,
              help="How many times to retry a judge call that hits HTTP 429 "
                   "before giving up on that pair. Backoff honors a retry-after "
                   "header when present, else exponential (2/4/8/16/32s). A pair "
                   "that exhausts its retries is skipped, not fatal.")
@click.option("--min-request-interval", type=float, default=None,
              help="Seconds to sleep between judge calls, to stay under a free tier's "
                   "requests-per-minute limit. Default 0 for OpenAI; auto-set to 12.0 "
                   "for --llm-provider=cerebras (its ~5 RPM free tier) unless you pass "
                   "a value explicitly.")
@click.option("--json-out", type=click.Path(), default=None,
              help="Also write findings to a JSON file. Written incrementally "
                   "(atomically, after each pair), so an interrupted run still "
                   "leaves a valid partial report.")
def run(user_id: str, config: str | None, top_k: int, min_similarity: float,
        similarity_threshold: float | None, page_size: int,
        embed_provider: str, llm_provider: str, llm_model: str | None,
        max_retries: int, min_request_interval: float | None, json_out: str | None):
    """Audit a single user's memory store for duplicates, contradictions, and staleness."""
    from mem0 import Memory  # imported lazily so `mem-audit --help` doesn't require mem0ai extras

    if config:
        import json as _json

        with open(config, "r", encoding="utf-8") as fh:
            cfg = _json.load(fh)
        client = Memory.from_config(cfg)
    else:
        client = Memory()

    embed_fn = github_models_embedder() if embed_provider == "github" else openai_embedder()

    if llm_provider == "cerebras":
        llm_call = (
            cerebras_llm_judge(model=llm_model, max_retries=max_retries)
            if llm_model
            else cerebras_llm_judge(max_retries=max_retries)
        )
    else:
        llm_call = (
            default_llm_judge(model=llm_model, max_retries=max_retries)
            if llm_model
            else default_llm_judge(max_retries=max_retries)
        )

    # RPM is the binding constraint on the free judge tiers (Cerebras is ~5 RPM
    # in 2026), not the daily token budget — so throttle between calls by
    # default there. Explicit --min-request-interval always wins.
    if min_request_interval is None:
        min_request_interval = 12.0 if llm_provider == "cerebras" else 0.0

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
        # Missing/misconfigured credentials for the chosen provider.
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
