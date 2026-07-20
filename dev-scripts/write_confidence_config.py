import json
import os

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"].strip()

config = {
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "path": "./confidence_test_qdrant_db",
            "collection_name": "mem_audit_confidence_test",
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

with open("confidence_config.json", "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2)

print("Wrote confidence_config.json")
