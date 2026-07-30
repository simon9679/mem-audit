"""
Offline tests for the provider preset table and the preset/escape-hatch
resolution logic. No network, no keys, no mem0 — key resolution is exercised
by asserting on the ValueError raised when the relevant env var is absent, and
model selection by injecting a recording client.
"""
import contextlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mem_audit.providers import (  # noqa: E402
    EMBED_PRESETS,
    JUDGE_PRESETS,
    PRESETS,
    EndpointSpec,
    embedder_from_preset,
    judge_from_preset,
    resolve_embedder,
    resolve_judge,
)


@contextlib.contextmanager
def _env_without(*names):
    """Temporarily remove env vars so a missing-key path is deterministic."""
    saved = {n: os.environ.pop(n, None) for n in names}
    try:
        yield
    finally:
        for n, v in saved.items():
            if v is not None:
                os.environ[n] = v


class _Item:
    def __init__(self, embedding):
        self.embedding = embedding


class _Resp:
    def __init__(self, data):
        self.data = data


class _RecordingEmbedClient:
    """Fake OpenAI-compatible embeddings client that records the model used."""

    def __init__(self):
        self.models = []
        self.embeddings = self

    def create(self, model, input):
        self.models.append(model)
        return _Resp([_Item([0.0, 0.0]) for _ in input])


def _expect_valueerror(fn):
    try:
        fn()
    except ValueError as e:
        return str(e)
    except KeyError as e:  # pragma: no cover - explicit contract: never KeyError
        raise AssertionError(f"expected ValueError, got KeyError: {e}")
    raise AssertionError("expected ValueError, nothing was raised")


# -- table integrity -------------------------------------------------------- #
def test_preset_table_integrity():
    assert PRESETS, "preset table must not be empty"
    for name, spec in PRESETS.items():
        assert isinstance(spec, EndpointSpec)
        assert spec.name == name
        assert spec.api_key_env and isinstance(spec.api_key_env, str)
        # Every endpoint must serve at least one role.
        assert spec.embed_model or spec.judge_model, f"{name!r} serves no role"
        assert isinstance(spec.max_batch_tokens, int) and spec.max_batch_tokens > 0
        assert isinstance(spec.max_batch_items, int) and spec.max_batch_items > 0
        assert isinstance(spec.min_request_interval, float)
        assert spec.min_request_interval >= 0.0


def test_role_lists_reflect_the_table():
    assert set(EMBED_PRESETS) == {n for n, s in PRESETS.items() if s.embed_model}
    assert set(JUDGE_PRESETS) == {n for n, s in PRESETS.items() if s.judge_model}


# -- model selection -------------------------------------------------------- #
def test_embedder_uses_preset_model_by_default():
    c = _RecordingEmbedClient()
    embedder_from_preset("openai", client=c)(["hello"])
    assert c.models == ["text-embedding-3-small"]


def test_embedder_applies_explicit_model_override():
    c = _RecordingEmbedClient()
    embedder_from_preset("openai", model_override="custom-embed-model", client=c)(["hello"])
    assert c.models == ["custom-embed-model"]


# -- ollama preset: local, keyless embeddings ------------------------------- #
def test_ollama_is_an_embedding_preset_only():
    assert "ollama" in EMBED_PRESETS
    assert "ollama" not in JUDGE_PRESETS


def test_ollama_embedder_uses_nomic_by_default():
    c = _RecordingEmbedClient()
    embedder_from_preset("ollama", client=c)(["hello"])
    assert c.models == ["nomic-embed-text"]


def test_ollama_preset_requires_no_api_key():
    # No OLLAMA_API_KEY / OPENAI_API_KEY in the environment: a keyless preset
    # (api_key_default set) must NOT raise the missing-key ValueError. Building
    # the real client may fail later if openai isn't installed (clean CI venv) —
    # that's a different error and fine; the point is no missing-key ValueError.
    with _env_without("OLLAMA_API_KEY", "OPENAI_API_KEY"):
        try:
            embedder_from_preset("ollama")
        except ValueError as e:
            raise AssertionError(f"ollama preset must not require a key: {e}")
        except Exception:
            pass  # e.g. ModuleNotFoundError('openai') in a clean venv — acceptable


# -- key resolution: ValueError naming the env var, never KeyError/None ----- #
def test_missing_judge_key_raises_valueerror_naming_env_var():
    with _env_without("CEREBRAS_API_KEY"):
        msg = _expect_valueerror(lambda: judge_from_preset("cerebras"))
        assert "CEREBRAS_API_KEY" in msg


def test_missing_embed_key_raises_valueerror_naming_env_var():
    with _env_without("OPENAI_API_KEY"):
        msg = _expect_valueerror(lambda: embedder_from_preset("openai"))
        assert "OPENAI_API_KEY" in msg


def test_unknown_preset_raises_valueerror_not_keyerror():
    msg = _expect_valueerror(lambda: embedder_from_preset("does-not-exist"))
    assert "does-not-exist" in msg


def test_judge_only_preset_has_no_embedder():
    # cerebras is a judge endpoint (embed_model=None) — asking for an embedder
    # is a clear ValueError, before any key lookup.
    msg = _expect_valueerror(lambda: embedder_from_preset("cerebras"))
    assert "embed" in msg.lower()


# -- flag precedence: explicit base_url is an escape hatch ------------------- #
def test_base_url_overrides_preset_key_env():
    # The cerebras preset would demand CEREBRAS_API_KEY; an explicit base_url +
    # api_key_env ignores the preset entirely, so the custom var name is what's
    # required.
    with _env_without("MY_CUSTOM_KEY", "CEREBRAS_API_KEY"):
        msg = _expect_valueerror(
            lambda: resolve_judge(
                "cerebras", base_url="https://example.com/v1", model="m",
                api_key_env="MY_CUSTOM_KEY",
            )
        )
        assert "MY_CUSTOM_KEY" in msg
        assert "CEREBRAS_API_KEY" not in msg


def test_preset_applies_when_no_explicit_flags():
    with _env_without("CEREBRAS_API_KEY"):
        msg = _expect_valueerror(lambda: resolve_judge("cerebras"))
        assert "CEREBRAS_API_KEY" in msg


def test_api_key_env_override_applies_without_base_url():
    with _env_without("OTHER_ENV", "OPENAI_API_KEY"):
        msg = _expect_valueerror(lambda: resolve_judge("openai", api_key_env="OTHER_ENV"))
        assert "OTHER_ENV" in msg


def test_embed_base_url_without_model_raises():
    msg = _expect_valueerror(lambda: resolve_embedder("openai", base_url="https://example.com"))
    assert "model" in msg.lower()


def test_llm_base_url_without_model_raises():
    msg = _expect_valueerror(lambda: resolve_judge("openai", base_url="https://example.com"))
    assert "model" in msg.lower()


if __name__ == "__main__":
    test_preset_table_integrity()
    test_role_lists_reflect_the_table()
    test_embedder_uses_preset_model_by_default()
    test_embedder_applies_explicit_model_override()
    test_ollama_is_an_embedding_preset_only()
    test_ollama_embedder_uses_nomic_by_default()
    test_ollama_preset_requires_no_api_key()
    test_missing_judge_key_raises_valueerror_naming_env_var()
    test_missing_embed_key_raises_valueerror_naming_env_var()
    test_unknown_preset_raises_valueerror_not_keyerror()
    test_judge_only_preset_has_no_embedder()
    test_base_url_overrides_preset_key_env()
    test_preset_applies_when_no_explicit_flags()
    test_api_key_env_override_applies_without_base_url()
    test_embed_base_url_without_model_raises()
    test_llm_base_url_without_model_raises()
    print("Provider preset + resolution tests passed.")
