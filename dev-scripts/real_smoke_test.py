import os

from mem0 import Memory

from mem_audit.providers import embedder_from_preset, judge_from_preset
from mem_audit.pipeline import run_audit
from mem_audit.report import print_report

CEREBRAS_API_KEY = os.environ["CEREBRAS_API_KEY"].strip()

# Local Ollama for embeddings (no key); requires `ollama pull nomic-embed-text`.
config = {
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "path": "./smoke_test_qdrant_db",
            "collection_name": "mem_audit_smoke_test",
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

client.add("My name is LGY", user_id="smoketest", infer=False)
client.add("My name is LGS", user_id="smoketest", infer=False)
client.add("I live in Berlin", user_id="smoketest", infer=False)

embed_fn = embedder_from_preset("ollama")
llm_call = judge_from_preset("cerebras", api_key=CEREBRAS_API_KEY)

# top-k instead of a fixed threshold now — no magic number to guess.
findings, total = run_audit(
    mem0_client=client,
    user_id="smoketest",
    embed_fn=embed_fn,
    llm_call=llm_call,
    top_k=5,
    min_similarity=0.3,
)

print_report(findings, total_memories=total, user_id="smoketest")

assert total == 3, f"expected 3 memories, got {total}"
print("\nSMOKE TEST PASSED: real Mem0 + local Ollama embeddings + Cerebras judge work end-to-end.")
print("(No longer asserting the judge's exact label — a real LLM may reasonably")
print(" call LGY/LGS an UPDATE rather than a CONTRADICTION; see chat for why.)")
