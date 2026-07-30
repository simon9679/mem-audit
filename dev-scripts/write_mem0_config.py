"""
Generates mem0_config.json pointing mem0 at a local Ollama server, so the real
`mem-audit run --config mem0_config.json` CLI path gets tested too. No API key
needed — requires a running Ollama with `ollama pull nomic-embed-text`.

Run this once, then use the printed mem-audit command.
"""
import json

config = {
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "path": "./realistic_test_qdrant_db",
            "collection_name": "mem_audit_realistic_test",
            "embedding_model_dims": 768,
        },
    },
    "embedder": {
        "provider": "openai",
        "config": {
            "model": "nomic-embed-text",
            "openai_base_url": "http://localhost:11434/v1",
            "api_key": "ollama",
        },
    },
    "llm": {
        "provider": "openai",
        "config": {
            "model": "llama3.2",
            "openai_base_url": "http://localhost:11434/v1",
            "api_key": "ollama",
        },
    },
}

with open("mem0_config.json", "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2)

print("Wrote mem0_config.json")
