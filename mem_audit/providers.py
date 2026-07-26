"""
Endpoint presets as data.

A "provider" here is not a distinct implementation — it's a set of parameters
(base URL, which env var holds the key, model ids, batch sizes, a default
throttle) handed to the generic OpenAI-compatible factories in
`embeddings.py` and `contradictions.py`. This module is the one place those
parameters live, so adding an endpoint is a row in a table, not a copied
function.

Import direction is one-way and deliberate: this module imports the generic
factories; the factories never import this module. If a detector or embedder
ever seems to need something from here, the abstraction has slipped — stop and
reconsider rather than adding a local import to break the cycle.

Scope note: the fields below are technical properties of an endpoint only. They
say nothing about the price, plan, or rate allowance of anyone's account — that
is not information this repository can know or promise.
"""
from __future__ import annotations

from dataclasses import dataclass

from mem_audit.detectors.contradictions import (
    DEFAULT_MAX_RETRIES,
    LLMCallFn,
    openai_compatible_judge,
)
from mem_audit.embeddings import EmbedFn, openai_compatible_embedder


@dataclass(frozen=True)
class EndpointSpec:
    name: str
    base_url: str | None          # None -> the client library's default base URL
    api_key_env: str              # name of the env var the key is read from
    embed_model: str | None       # None -> this endpoint is not used for embeddings
    judge_model: str | None       # None -> this endpoint is not used as a judge
    max_batch_tokens: int         # per-request token budget for the embedding pass
    max_batch_items: int          # per-request item cap for the embedding pass
    # Conservative default delay between judge calls for an endpoint that limits
    # request frequency. Set 0 if your account allows more. Not a claim about any
    # particular plan's allowance.
    min_request_interval: float


# Batch sizes are per-request ceilings the endpoint enforces on the embedding
# call; the OpenAI values double as the generic defaults in embeddings.py, and
# the GitHub endpoint has a tighter per-request budget so it carries smaller
# numbers here. cerebras is a judge-only endpoint (embed_model=None), so its
# batch fields are inert and just mirror the OpenAI defaults.
PRESETS: dict[str, EndpointSpec] = {
    "openai": EndpointSpec(
        name="openai",
        base_url=None,
        api_key_env="OPENAI_API_KEY",
        embed_model="text-embedding-3-small",
        judge_model="gpt-4o-mini",
        max_batch_tokens=250_000,
        max_batch_items=128,
        min_request_interval=0.0,
    ),
    "github": EndpointSpec(
        name="github",
        base_url="https://models.github.ai/inference",
        api_key_env="GITHUB_TOKEN",
        embed_model="openai/text-embedding-3-small",
        judge_model=None,
        max_batch_tokens=6_000,
        max_batch_items=64,
        min_request_interval=0.0,
    ),
    "cerebras": EndpointSpec(
        name="cerebras",
        base_url="https://api.cerebras.ai/v1",
        api_key_env="CEREBRAS_API_KEY",
        embed_model=None,
        # The model catalog for this endpoint has changed more than once; if this
        # default isn't in your account, check client.models.list() and pass an
        # explicit model.
        judge_model="gpt-oss-120b",
        max_batch_tokens=250_000,
        max_batch_items=128,
        min_request_interval=12.0,
    ),
}

# Only the presets that can actually serve each role — used to build the CLI's
# provider choices so a judge-only endpoint isn't offered as an embedder, etc.
EMBED_PRESETS = tuple(sorted(n for n, s in PRESETS.items() if s.embed_model))
JUDGE_PRESETS = tuple(sorted(n for n, s in PRESETS.items() if s.judge_model))


def _require_preset(name: str) -> EndpointSpec:
    try:
        return PRESETS[name]
    except KeyError:
        raise ValueError(
            f"unknown provider preset {name!r}; known presets: {sorted(PRESETS)}"
        )


def embedder_from_preset(
    name: str,
    model_override: str | None = None,
    api_key_env_override: str | None = None,
    api_key: str | None = None,
    client=None,
) -> EmbedFn:
    """Build an embedder from a named preset, with optional per-field overrides."""
    spec = _require_preset(name)
    model = model_override or spec.embed_model
    if model is None:
        raise ValueError(
            f"provider {name!r} is not an embedding endpoint (no embed_model); "
            f"pass model_override or choose a different provider."
        )
    return openai_compatible_embedder(
        model=model,
        base_url=spec.base_url,
        api_key=api_key,
        api_key_env=api_key_env_override or spec.api_key_env,
        max_batch_tokens=spec.max_batch_tokens,
        max_batch_items=spec.max_batch_items,
        client=client,
    )


def judge_from_preset(
    name: str,
    model_override: str | None = None,
    api_key_env_override: str | None = None,
    api_key: str | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    client=None,
) -> LLMCallFn:
    """Build a judge from a named preset, with optional per-field overrides."""
    spec = _require_preset(name)
    model = model_override or spec.judge_model
    if model is None:
        raise ValueError(
            f"provider {name!r} is not a judge endpoint (no judge_model); "
            f"pass model_override or choose a different provider."
        )
    return openai_compatible_judge(
        model=model,
        base_url=spec.base_url,
        api_key=api_key,
        api_key_env=api_key_env_override or spec.api_key_env,
        max_retries=max_retries,
        client=client,
    )


def resolve_embedder(
    provider: str,
    base_url: str | None = None,
    model: str | None = None,
    api_key_env: str | None = None,
    api_key: str | None = None,
    client=None,
) -> EmbedFn:
    """
    Resolve an embedder from CLI-style inputs.

    Precedence: an explicit base_url is an escape hatch — the named preset is
    ignored entirely, and an explicit model is then required (there is no preset
    to supply a default). Without a base_url the named preset is used, with the
    model / api_key_env overrides applied on top.
    """
    if base_url:
        if not model:
            raise ValueError(
                "an explicit embedding base URL requires an explicit model "
                "(--embed-model): there is no preset to supply a default model."
            )
        return openai_compatible_embedder(
            model=model,
            base_url=base_url,
            api_key=api_key,
            api_key_env=api_key_env or "OPENAI_API_KEY",
            client=client,
        )
    return embedder_from_preset(
        provider,
        model_override=model,
        api_key_env_override=api_key_env,
        api_key=api_key,
        client=client,
    )


def resolve_judge(
    provider: str,
    base_url: str | None = None,
    model: str | None = None,
    api_key_env: str | None = None,
    api_key: str | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    client=None,
) -> LLMCallFn:
    """
    Resolve a judge from CLI-style inputs.

    Same precedence as resolve_embedder: an explicit base_url ignores the preset
    and requires an explicit model (--llm-model); otherwise the named preset is
    used with overrides on top.
    """
    if base_url:
        if not model:
            raise ValueError(
                "an explicit judge base URL requires an explicit model "
                "(--llm-model): there is no preset to supply a default model."
            )
        return openai_compatible_judge(
            model=model,
            base_url=base_url,
            api_key=api_key,
            api_key_env=api_key_env or "OPENAI_API_KEY",
            max_retries=max_retries,
            client=client,
        )
    return judge_from_preset(
        provider,
        model_override=model,
        api_key_env_override=api_key_env,
        api_key=api_key,
        max_retries=max_retries,
        client=client,
    )
