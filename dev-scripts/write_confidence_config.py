"""Writes confidence_config.json pointing mem0 at a local Ollama server
(embeddings via nomic-embed-text). No API key needed. Requires a running Ollama
with `ollama pull nomic-embed-text`."""
import json

config = {
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "path": "./confidence_test_qdrant_db",
            "collection_name": "mem_audit_confidence_test",
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

with open("confidence_config.json", "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2)

print("Wrote confidence_config.json")
