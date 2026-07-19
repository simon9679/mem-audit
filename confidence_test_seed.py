"""
Confidence test: seeds a larger, harder, more realistic memory store with
KNOWN ground truth, so after running the real CLI we can compute actual
precision/recall — not just "it didn't crash".

Includes deliberately tricky cases:
- paraphrased duplicates (not just template swaps)
- a near-miss pair that's topically related but NOT a duplicate/contradiction
  (tests false positive rate, the harder direction to get right)
- multiple unrelated facts as noise

Run this once, then run the real CLI against it (instructions printed at
the end), then run analyze_confidence_test.py against report.json.
"""
import os

from mem0 import Memory

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

client = Memory.from_config(config)

# (id_tag, text) — id_tag is just for our own ground-truth bookkeeping,
# not passed to Mem0 (Mem0 assigns its own UUIDs).
MEMORIES = [
    # --- duplicates: paraphrased, not template swaps (harder) ---
    ("dup1a", "I've been vegetarian for about five years now"),
    ("dup1b", "Haven't eaten meat in roughly five years"),

    ("dup2a", "My commute to work takes almost an hour each way"),
    ("dup2b", "Getting to the office eats up close to an hour, one direction"),

    ("dup3a", "I graduated with a degree in mechanical engineering"),
    ("dup3b", "My degree is in mechanical engineering"),

    # --- contradictions: direct opposites ---
    ("contra1a", "I'm allergic to peanuts"),
    ("contra1b", "Peanuts are one of my favorite snacks"),

    ("contra2a", "I don't have any pets"),
    ("contra2b", "My dog needs to go to the vet next week"),

    # --- updates: life changes over time, plausible sequence ---
    ("upd1a", "I'm currently single"),
    ("upd1b", "My girlfriend and I just moved in together"),

    ("upd2a", "I work as a barista at a local cafe"),
    ("upd2b", "Just started a new job as a data analyst"),

    # --- near-miss: related topic, NOT actually duplicate/contradiction
    # (this is the hard case — tests false positive rate specifically) ---
    ("nearmiss_a", "I love hiking in the mountains on weekends"),
    ("nearmiss_b", "I'm training for a half-marathon next spring"),

    # --- unrelated noise (should produce zero findings) ---
    ("noise1", "My favorite season is autumn"),
    ("noise2", "I play the violin, though not very well"),
    ("noise3", "I'm reading a biography of Marie Curie right now"),
    ("noise4", "I collect vintage postcards"),
    ("noise5", "My grandmother taught me how to bake bread"),
    ("noise6", "I volunteer at an animal shelter once a month"),
    ("noise7", "I'm learning conversational Japanese"),
    ("noise8", "My favorite movie genre is science fiction"),
]

for tag, text in MEMORIES:
    client.add(text, user_id="confidencetest", infer=False)

print(f"Seeded {len(MEMORIES)} memories into ./confidence_test_qdrant_db under user_id='confidencetest'")
print("\nGround truth (for later comparison — do not peek at results before running):")
print("  Expected DUPLICATE pairs: dup1, dup2, dup3 (3 pairs)")
print("  Expected CONTRADICTION pairs: contra1, contra2 (2 pairs)")
print("  Expected UPDATE/stale pairs: upd1, upd2 (2 pairs)")
print("  Expected to NOT be flagged: nearmiss pair, all 8 noise facts")
print("\nNow run the real CLI:")
print("  mem-audit run --user-id confidencetest --config confidence_config.json "
      "--embed-provider github --llm-provider cerebras --json-out confidence_report.json")
