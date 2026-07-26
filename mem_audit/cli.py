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


def _expected_key_env(base_url: str | None, api_key_env: str | None, provider: str) -> str:
    """The env var whose absence caused a missing-key error, for the chosen endpoint."""
    if base_url:
        return api_key_env or "OPENAI_API_KEY"
    return api_key_env or PRESETS[provider].api_key_env


def _no_key_message(role: str, expected_env: str, provider_flag: str,
                    presets, base_url_flag: str, model_flag: str) -> str:
    """
    CLI-facing guidance for a missing endpoint key. Deliberately in command-line
    terms (env var, flags) — never the library's function name or its Python
    keyword arguments — and it lists the alternative endpoints from the preset
    table so it can't
    drift when a preset is added. It names the variable actually expected for the
    chosen provider, which is not always OPENAI_API_KEY.
    """
    preset_list = " | ".join(presets)
    return (
        f"No API key found for the {role} endpoint. Do one of:\n"
        f"  - set the {expected_env} environment variable; or\n"
        f"  - choose a different {role} endpoint: {provider_flag} < {preset_list} >; or\n"
        f"  - point at your own OpenAI-compatible endpoint: "
        f"{base_url_flag} <url> {model_flag} <model>."
    )


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
    # Build mem-audit's own embedder/judge clients FIRST — before touching mem0 —
    # so an argument mistake is reported as an argument mistake, not masked by
    # mem0's own (later) initialization failure.
    #
    # Within that, validate the STRUCTURE of every argument before resolving any
    # key: a base URL with no model is a mistake the user just made, whereas a
    # missing key is ambient environment state, so the structural error wins —
    # and it must point at whichever endpoint (embedder or judge) it's on.
    if embed_base_url and not embed_model:
        raise click.ClickException(
            "--embed-base-url needs --embed-model too: with a custom base URL "
            "there is no preset to supply a default embedding model."
        )
    if llm_base_url and not llm_model:
        raise click.ClickException(
            "--llm-base-url needs --llm-model too: with a custom base URL there "
            "is no preset to supply a default judge model."
        )

    try:
        embed_fn = resolve_embedder(
            embed_provider,
            base_url=embed_base_url,
            model=embed_model,
            api_key_env=embed_api_key_env,
        )
    except ValueError:
        # Structure is already validated above, so this is a missing key. Turn
        # the library error into command-line guidance.
        raise click.ClickException(_no_key_message(
            "embedding", _expected_key_env(embed_base_url, embed_api_key_env, embed_provider),
            "--embed-provider", EMBED_PRESETS, "--embed-base-url", "--embed-model",
        ))

    try:
        llm_call = resolve_judge(
            llm_provider,
            base_url=llm_base_url,
            model=llm_model,
            api_key_env=llm_api_key_env,
            max_retries=max_retries,
        )
    except ValueError:
        raise click.ClickException(_no_key_message(
            "judge", _expected_key_env(llm_base_url, llm_api_key_env, llm_provider),
            "--llm-provider", JUDGE_PRESETS, "--llm-base-url", "--llm-model",
        ))

    from mem0 import Memory  # imported lazily so `mem-audit --help` doesn't require mem0ai extras

    # mem0 brings up its OWN embedder/LLM from its OWN config when the client is
    # created; that is independent of the --embed-provider/--llm-provider flags
    # resolved above. Wrap it so that failure is a clean CLI error, with a
    # message tailored to whether a --config was supplied.
    try:
        if config:
            import json as _json

            with open(config, "r", encoding="utf-8") as fh:
                cfg = _json.load(fh)
            client = Memory.from_config(cfg)
        else:
            client = Memory()
    except Exception as e:  # noqa: BLE001 — surface mem0's own init failure as a clean CLI error
        if config:
            raise click.ClickException(
                f"mem0 read your config at '{config}' but could not initialize "
                f"from it. mem0 builds its OWN embedder/LLM from that file, and "
                f"failed to bring them up. Most likely the config is missing an "
                f"'embedder'/'llm' section, or names a provider you don't have "
                f"credentials for. (mem-audit's --embed-provider/--llm-provider do "
                f"not affect mem0's own clients.) Underlying error: {e}"
            )
        raise click.ClickException(
            "mem0 could not initialize its default client. This happens inside "
            "mem0, before mem-audit runs: with no --config, mem0 builds its OWN "
            "embedder/LLM from its default configuration, and mem-audit's "
            "--embed-provider/--llm-provider flags do not affect that. The most "
            "common cause is a missing OPENAI_API_KEY for mem0's default embedder. "
            "Fix it by passing --config with a mem0 config JSON that uses a "
            f"provider you have credentials for. Underlying error: {e}"
        )

    # Default the inter-call throttle from the chosen judge preset (0 for the
    # escape-hatch path, which has no preset). An explicit value always wins.
    if min_request_interval is None:
        min_request_interval = 0.0 if llm_base_url else PRESETS[llm_provider].min_request_interval

    # Run metadata, so a --json-out report records how it was produced (and can
    # be compared against another run). Populated further by the pipeline
    # (memories_scanned, candidate_pairs, judge_verdicts). No API keys ever.
    import datetime as _datetime

    from mem_audit import __version__ as _version

    embed_model_used = embed_model or PRESETS[embed_provider].embed_model
    judge_model_used = llm_model or PRESETS[llm_provider].judge_model
    report_metadata: dict = {
        "tool": "mem-audit",
        "version": _version,
        "run_at": _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
        "user_id": user_id,
        "embedder": {
            "provider": "custom" if embed_base_url else embed_provider,
            "model": embed_model_used,
            "base_url": embed_base_url or PRESETS[embed_provider].base_url,
        },
        "judge": {
            "provider": "custom" if llm_base_url else llm_provider,
            "model": judge_model_used,
            "base_url": llm_base_url or PRESETS[llm_provider].base_url,
        },
        "params": {
            "top_k": top_k,
            "min_similarity": min_similarity,
            "similarity_threshold": similarity_threshold,
            "max_retries": max_retries,
            "min_request_interval": min_request_interval,
            "page_size": page_size,
        },
    }
    run_line = (
        f"embedder: {embed_model_used} · judge: {judge_model_used} · top-k: {top_k}"
    )

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
            report_metadata=report_metadata,
        )
    except RuntimeError as e:
        raise click.ClickException(str(e))
    except ValueError as e:
        # Data-shape problems surfaced mid-pipeline (e.g. embed_fn returned a
        # different number of vectors than inputs — see duplicates.py). Missing
        # credentials are already handled when the clients are built above.
        raise click.ClickException(str(e))

    print_report(findings, total_memories=total, user_id=user_id, run_line=run_line)

    if skipped_pairs:
        click.echo(
            f"\n{skipped_pairs} pair(s) skipped due to rate limits — re-run to "
            f"cover them, or raise --max-retries / --min-request-interval.",
            err=True,
        )

    if json_out:
        # run_audit already flushed findings to json_out incrementally after
        # every pair; this final write just guarantees the file exists (as the
        # {metadata, findings} object) even when there were zero candidate pairs.
        export_json(findings, json_out, metadata=report_metadata)
        click.echo(f"\nFindings written to {json_out}")


if __name__ == "__main__":
    main()
