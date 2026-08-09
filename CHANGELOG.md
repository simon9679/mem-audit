# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `audit/` — a self-contained external audit of Mem0's own consistency,
  separate from mem-audit's tool-accuracy measurement in `docs/`. Covers three
  silent-write-loss defects measured on mem0ai 1.0.11 (all confirmed fixed
  upstream in 2.x) and one that isn't a defect: extraction non-reproducibility
  at `temperature=0`, still present on mem0ai 2.0.17. Consolidated report in
  `audit/AUDIT_mem0.md`, with pre-registrations, per-stage results, the
  silent-loss write-up, and the harness/probe code that produced the numbers.
  Linked from the README under "Is Mem0 itself reproducible?".

## [0.1.0] - 2026-07-31

First public release.

### Breaking

- `--json-out` now writes an object `{"metadata": ..., "findings": [...]}`
  instead of a bare findings array (#10).
- CLI flags changed:
  - Added `--embed-base-url`, `--embed-model`, `--embed-api-key-env`,
    `--llm-base-url`, `--llm-api-key-env` (#7).
  - `--embed-provider` / `--llm-provider` choices are generated from the preset
    table; accepted values are `[ollama|openai]` for the embedder and
    `[cerebras|openai]` for the judge (#7, #12, #13).
- Removed the `github` embeddings preset — GitHub Models was fully retired on
  July 30, 2026 (#13).
- Removed the four single-endpoint Python factories (`openai_embedder`,
  `github_models_embedder`, `default_llm_judge`, `cerebras_llm_judge`), replaced
  by generic `openai_compatible_embedder` / `openai_compatible_judge` (#7).

### Added

- `ollama` embeddings preset — local, no API key (#12).
- Run metadata in `--json-out` reports: tool version, provider and the actual
  model names, all parameters, candidate-pair count, and the judge's verdict
  distribution (#10).
- Provider presets as data (an `EndpointSpec` table) plus escape-hatch flags for
  any OpenAI-compatible endpoint (#7).
- Mechanical confidence scoring by memory id
  (`dev-scripts/analyze_confidence_test.py`) and a test that locks the documented
  numbers (`tests/test_confidence_analysis.py`) (#10).
- Accuracy postmortem — `docs/accuracy-postmortem.md`.
- First-run guidance: command-line missing-key errors that name the expected env
  var and list alternatives; a note that mem0 needs its own embedder config; a
  mem0 telemetry opt-out note (#8, #9).

### Changed

- Report table is sorted by severity, highest first (contradictions on top) (#6).
- README restructured (install → offline demo → two-config setup → endpoint
  choice → run) with a call-count cost model; "bring your own OpenAI key" and
  local Ollama are the documented embedding paths (#8, #11, #12, #13).

### Fixed

- Report severity sort was inverted (LOW on top) (#6).
- The id tiebreaker now applies when two records share a `created_at` (#6).
- Cursor pagination has hard page and record ceilings — no unbounded request
  loop on a broken cursor (#6).
- Finding summaries truncate on a word boundary instead of mid-word (#6).
- Missing-credential problems surface as clean CLI errors, before mem0
  initialization, rather than tracebacks; the provider key check runs before
  `openai` is imported (#7, #9).

### Removed

- Dead `fetch_history` connector method whose docstring misdescribed it (#6).

[0.1.0]: https://github.com/simon9679/mem-audit/releases/tag/v0.1.0
