"""
Offline CLI tests. Provider arguments are validated (structure first, then keys)
BEFORE mem0 is imported, and a missing key is resolved before openai is imported,
so these paths run with neither mem0ai nor openai installed (as CI is).

Covers:
- an argument mistake (base URL without model) is reported as such, not masked
  by a later mem0 failure — for both the embedder and the judge;
- a missing key produces command-line guidance, with no library internals
  (`openai_compatible_...`, `api_key=`) leaking into the message.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from click.testing import CliRunner  # noqa: E402

from mem_audit.cli import _no_key_message, main  # noqa: E402

# Remove every key var so the missing-key path is deterministic regardless of
# the local environment (CliRunner maps None -> os.environ.pop).
_NO_KEYS = {"OPENAI_API_KEY": None, "GITHUB_TOKEN": None, "CEREBRAS_API_KEY": None}


def _run(args, env=None):
    return CliRunner().invoke(main, ["run", "--user-id", "alice", *args], env=env or dict(_NO_KEYS))


def _assert_no_library_internals(output):
    assert "openai_compatible_" not in output, output
    assert "api_key=" not in output, output


# -- argument structure is checked before keys, for both endpoints (spec 4) -- #
def test_embed_base_url_without_model_reports_model_before_mem0():
    result = _run(["--embed-base-url", "https://example.com/v1"])
    assert result.exit_code != 0, result.output
    assert "model" in result.output.lower(), result.output
    assert "mem0" not in result.output.lower(), result.output


def test_llm_base_url_without_model_reports_model_not_missing_key():
    # Empty environment: the missing embedder key would also be a real problem,
    # but the user just mistyped the judge args, so the model error must win.
    result = _run(["--llm-base-url", "https://example.com/v1"])
    assert result.exit_code != 0, result.output
    out = result.output.lower()
    assert "--llm-model" in out, result.output
    assert "no api key" not in out, result.output  # not masked by a key error
    assert "mem0" not in out, result.output


# -- missing key -> CLI-language guidance, no library internals (spec 1) ----- #
def test_default_missing_key_message_is_cli_friendly():
    result = _run([])  # defaults: embed=openai
    assert result.exit_code != 0, result.output
    _assert_no_library_internals(result.output)
    assert "OPENAI_API_KEY" in result.output, result.output  # the expected var
    assert "--embed-provider" in result.output, result.output  # the alternative


def test_missing_key_message_names_the_expected_env_var():
    # The named variable is the one actually expected — here a custom var from
    # --embed-api-key-env on the escape-hatch path, not always OPENAI_API_KEY.
    result = _run([
        "--embed-base-url", "https://example.com/v1",
        "--embed-model", "some-model",
        "--embed-api-key-env", "MY_EMBED_KEY",
    ], env={"OPENAI_API_KEY": None, "MY_EMBED_KEY": None})
    assert result.exit_code != 0, result.output
    _assert_no_library_internals(result.output)
    assert "MY_EMBED_KEY" in result.output, result.output


def test_cerebras_llm_command_still_gives_clean_message():
    # The embedder (openai) resolves first and fails on its own key here; the
    # message must still be clean and actionable, with no library internals.
    result = _run(["--llm-provider", "cerebras"])
    assert result.exit_code != 0, result.output
    _assert_no_library_internals(result.output)
    assert "environment variable" in result.output, result.output


# -- judge-branch message content (can't reach it via CLI in an openai-free
#    venv, since a successful embedder resolution would import openai) -------- #
def test_no_key_message_for_judge_names_cerebras_var_and_flags():
    msg = _no_key_message(
        "judge", "CEREBRAS_API_KEY", "--llm-provider", ("openai", "cerebras"),
        "--llm-base-url", "--llm-model",
    )
    assert "CEREBRAS_API_KEY" in msg
    assert "--llm-provider" in msg
    assert "--llm-model" in msg
    _assert_no_library_internals(msg)


if __name__ == "__main__":
    test_embed_base_url_without_model_reports_model_before_mem0()
    test_llm_base_url_without_model_reports_model_not_missing_key()
    test_default_missing_key_message_is_cli_friendly()
    test_missing_key_message_names_the_expected_env_var()
    test_cerebras_llm_command_still_gives_clean_message()
    test_no_key_message_for_judge_names_cerebras_var_and_flags()
    print("CLI argument + missing-key message tests passed.")
