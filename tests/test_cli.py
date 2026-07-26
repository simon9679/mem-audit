"""
Offline CLI tests. Provider arguments are resolved and validated BEFORE mem0 is
imported, so an argument error surfaces without mem0ai/openai installed (as CI
is). This is the regression guard for "an argument mistake must be reported as
an argument mistake, not masked by a later mem0 initialization failure."
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from click.testing import CliRunner  # noqa: E402

from mem_audit.cli import main  # noqa: E402


def test_embed_base_url_without_model_reports_model_before_mem0():
    # --embed-base-url is an escape hatch that requires --embed-model. The error
    # must be about the missing model and must be reached before mem0 is even
    # imported — not a mem0 initialization message. It runs here with neither
    # openai nor mem0 installed precisely because it returns before importing
    # them, which is the whole point of resolving providers first.
    result = CliRunner().invoke(
        main, ["run", "--user-id", "alice", "--embed-base-url", "https://example.com/v1"]
    )
    assert result.exit_code != 0, result.output
    out = result.output.lower()
    assert "model" in out, result.output
    assert "mem0" not in out, result.output  # not masked by a mem0 message


if __name__ == "__main__":
    test_embed_base_url_without_model_reports_model_before_mem0()
    print("CLI argument tests passed.")
