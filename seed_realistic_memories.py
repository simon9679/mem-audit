"""
Seeds a local Mem0 store with a realistic, varied set of memories —
duplicates, contradictions, updates, and unrelated facts mixed together,
closer to what a real companion-bot memory store looks like than the
3-fact smoke test. Run this ONCE, then run the real `mem-audit` CLI
against the resulting store (see instructions printed at the end).
"""
import os

from mem0 import Memory

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
      "--embed-provider github --llm-provider cerebras --json-out report.json")
