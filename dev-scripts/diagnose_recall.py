"""
Diagnoses WHY the 3 missed pairs (contra2, upd1, upd2) weren't caught:
were they never selected as candidates by the cheap embedding pass, or
were they judged and dismissed by the LLM?

Run this AFTER confidence_test_seed.py has already populated the store
(reuses the same local Qdrant db, doesn't reseed).
"""
import os

from mem0 import Memory

from mem_audit.connectors.mem0_connector import Mem0Connector
from mem_audit.embeddings import cosine_similarity_matrix
from mem_audit.detectors.duplicates import find_duplicate_candidates
from mem_audit.detectors.contradictions import judge_pair
from mem_audit.providers import embedder_from_preset, judge_from_preset

CEREBRAS_API_KEY = os.environ["CEREBRAS_API_KEY"].strip()

# Local Ollama for embeddings (no key); requires `ollama pull nomic-embed-text`.
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

client = Memory.from_config(config)
connector = Mem0Connector(client)
records = connector.fetch_all(user_id="confidencetest")
print(f"Fetched {len(records)} records\n")

embed_fn = embedder_from_preset("ollama")
texts = [r.text for r in records]
vectors = embed_fn(texts)
sims = cosine_similarity_matrix(vectors)

MISSED_PAIRS = [
    ("I don't have any pets", "My dog needs to go to the vet next week"),
    ("I'm currently single", "My girlfriend and I just moved in together"),
    ("I work as a barista at a local cafe", "Just started a new job as a data analyst"),
]

text_to_idx = {r.text: i for i, r in enumerate(texts) and enumerate(records)}
text_to_idx = {r.text: i for i, r in enumerate(records)}

print("=== Raw cosine similarity for the 3 missed pairs ===")
for a_text, b_text in MISSED_PAIRS:
    i, j = text_to_idx[a_text], text_to_idx[b_text]
    score = float(sims[i, j])
    print(f"  {score:.4f}   '{a_text}' <-> '{b_text}'")

print("\n=== Were they in each other's top-5 nearest neighbors? ===")
for a_text, b_text in MISSED_PAIRS:
    i, j = text_to_idx[a_text], text_to_idx[b_text]
    row_i = sims[i].copy()
    row_i[i] = -2
    top5_of_i = set(row_i.argsort()[-5:])
    row_j = sims[j].copy()
    row_j[j] = -2
    top5_of_j = set(row_j.argsort()[-5:])
    in_top5 = (j in top5_of_i) or (i in top5_of_j)
    print(f"  in top-5: {in_top5}   '{a_text[:40]}' <-> '{b_text[:40]}'")

print("\n=== If they WERE candidates, what did the real judge actually say? ===")
llm_call = judge_from_preset("cerebras", api_key=CEREBRAS_API_KEY)
for a_text, b_text in MISSED_PAIRS:
    i, j = text_to_idx[a_text], text_to_idx[b_text]
    result = judge_pair(records[i], records[j], llm_call)
    print(f"  JUDGE SAID: {result.label} — {result.rationale}")
    print(f"    for '{a_text}' <-> '{b_text}'")
