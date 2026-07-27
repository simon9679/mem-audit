"""
Confidence test: seeds a larger, harder, more realistic memory store with
KNOWN ground truth, so after running the real CLI we can compute actual
precision/recall mechanically — not by eyeballing paraphrased summaries.

Includes deliberately tricky cases:
- paraphrased duplicates (not just template swaps)
- a near-miss pair that's topically related but NOT a duplicate/contradiction
  (tests false positive rate, the harder direction to get right)
- multiple unrelated facts as noise

Because Mem0 assigns its own UUIDs, this script captures the id it gets back for
each seeded fact and writes a ground-truth map (pair name -> the two Mem0 ids,
plus the expected finding type) to confidence_ground_truth.json, right next to
the config. analyze_confidence_test.py reads that map and the run's report and
scores by id — no human matching of paraphrased text.

Run this once, then run the real CLI (command printed at the end), then run
analyze_confidence_test.py.
"""
import json
import os

from mem0 import Memory

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"].strip()

GROUND_TRUTH_PATH = "confidence_ground_truth.json"

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

# (id_tag, text) — id_tag is our own ground-truth bookkeeping, not passed to Mem0.
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

# Ground-truth pairs: pair name -> (expected finding type, [tag_a, tag_b]).
# The type is what a correct run should label the pair: mem-audit reports an
# UPDATE as FindingType.STALE, hence "stale" for the upd* pairs.
PAIR_TAGS = {
    "dup1": ("duplicate", ["dup1a", "dup1b"]),
    "dup2": ("duplicate", ["dup2a", "dup2b"]),
    "dup3": ("duplicate", ["dup3a", "dup3b"]),
    "contra1": ("contradiction", ["contra1a", "contra1b"]),
    "contra2": ("contradiction", ["contra2a", "contra2b"]),
    "upd1": ("stale", ["upd1a", "upd1b"]),
    "upd2": ("stale", ["upd2a", "upd2b"]),
}


def _added_id(result) -> str:
    """Pull the created memory id out of Mem0's add() return value."""
    results = result.get("results", result) if isinstance(result, dict) else result
    return str(results[0]["id"])


tag_to_id = {}
for tag, text in MEMORIES:
    tag_to_id[tag] = _added_id(client.add(text, user_id="confidencetest", infer=False))

pairs = {
    name: {"type": ftype, "memory_ids": [tag_to_id[a], tag_to_id[b]]}
    for name, (ftype, (a, b)) in PAIR_TAGS.items()
}
ground_truth = {
    "user_id": "confidencetest",
    "tag_to_id": tag_to_id,
    "pairs": pairs,
    # Facts that must never appear in any finding (near-miss trap + noise).
    "expected_clean_tags": [t for t, _ in MEMORIES if t.startswith(("nearmiss", "noise"))],
}

with open(GROUND_TRUTH_PATH, "w", encoding="utf-8") as fh:
    json.dump(ground_truth, fh, ensure_ascii=False, indent=2)

print(f"Seeded {len(MEMORIES)} memories into ./confidence_test_qdrant_db under user_id='confidencetest'")
print(f"Wrote ground-truth id map to {GROUND_TRUTH_PATH} "
      f"({len(pairs)} planted pairs, {len(ground_truth['expected_clean_tags'])} clean facts)")
print("\nNow run the real CLI:")
print("  mem-audit run --user-id confidencetest --config confidence_config.json "
      "--embed-provider github --llm-provider cerebras --json-out confidence_report.json")
print("Then score it:")
print("  python dev-scripts/analyze_confidence_test.py")
