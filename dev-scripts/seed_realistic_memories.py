"""
Seeds a local Mem0 store with a realistic, varied set of memories —
duplicates, contradictions, updates, and unrelated facts mixed together,
closer to what a real companion-bot memory store looks like than the
3-fact smoke test. Run this ONCE, then run the real `mem-audit` CLI
against the resulting store (see instructions printed at the end).
"""
from mem0 import Memory

# Local Ollama for embeddings (no key); requires `ollama pull nomic-embed-text`.
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

client = Memory.from_config(config)

MEMORIES = [
    # near-duplicates (should be flagged as duplicate)
    "User has a cat",
    "User owns a cat named Whiskers",

    "User enjoys hiking on weekends",
    "User likes to go hiking when the weather is nice",

    # contradiction / preference update
    "User prefers Python over JavaScript",
    "User mostly codes in TypeScript now",

    "User dislikes coffee",
    "User drinks coffee every morning",

    # location contradiction
    "User lives in Berlin",
    "User currently lives in Kharkiv",

    # unrelated facts (no pair, should not be flagged)
    "User works as a software developer",
    "User is building an AI companion app",
    "User's favorite color is blue",
    "User has two younger siblings",
    "User is learning to play the guitar",
]

for text in MEMORIES:
    client.add(text, user_id="realistictest", infer=False)

print(f"Seeded {len(MEMORIES)} memories into ./realistic_test_qdrant_db under user_id='realistictest'")
print("\nNow run the actual CLI against it:")
print("  mem-audit run --user-id realistictest --config mem0_config.json "
      "--embed-provider ollama --llm-provider cerebras --json-out report.json")
