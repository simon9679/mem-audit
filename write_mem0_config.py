"""
Generates mem0_config.json from env vars, so the real `mem-audit run
--config mem0_config.json` CLI path gets tested too (everything so far
went through a custom Python script, never the actual CLI entry point).

Run this once, then use the printed mem-audit command.
"""
import json
import os

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"].strip()

config = {
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "path": "./realistic_test_qdrant_db",
            "collection_name": "mem_audit_realistic_test",
        },
    },
    "embedder": {
        "provider": "openai",
        "config": {
            "model": "openai/text-embedding-3-small",
            "openai_base_url": "https://models.github.ai/inference",
            "api_key": GITHUB_TOKEN,
        },
    },
    "llm": {
        "provider": "openai",
        "config": {
            "openai_base_url": "https://models.github.ai/inference",
            "api_key": GITHUB_TOKEN,
        },
    },
}

with open("mem0_config.json", "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2)

print("Wrote mem0_config.json")
