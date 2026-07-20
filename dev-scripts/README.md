# dev-scripts

Throwaway scripts used to validate mem-audit against real Mem0 instances
during development — not part of the package, not installed, not covered
by CI. Kept for reproducibility, not polish.

Run these from the **repo root**, not from inside this folder — they
write config/db files relative to the current directory:

```bash
python dev-scripts/write_confidence_config.py
python dev-scripts/confidence_test_seed.py
mem-audit run --user-id confidencetest --config confidence_config.json \
  --embed-provider github --llm-provider cerebras --json-out confidence_report.json
python dev-scripts/analyze_confidence_test.py
```

- `write_mem0_config.py` / `seed_realistic_memories.py` — first real-data
  smoke test (3 → 15 facts), superseded by the confidence test below.
- `write_confidence_config.py` / `confidence_test_seed.py` /
  `analyze_confidence_test.py` — the 24-fact ground-truth accuracy test
  cited in the main README's "Measured accuracy" section.
- `diagnose_recall.py` — one-off diagnostic that found the
  `min_similarity` floor bug (0.3 → 0.05 fix, see commit history).
- `real_smoke_test.py` — original 3-fact real-API smoke test, superseded
  by the above.

Needs `GITHUB_TOKEN` and `CEREBRAS_API_KEY` env vars set. None of these
scripts contain credentials — they read from the environment.
