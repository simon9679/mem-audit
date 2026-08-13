# PREREG - entity swap falsification of symdiff_probe.py

Registered before the check is run. The fixture, criterion, and predictions
below are committed in this file; `validate_symdiff_probe.py` is modified only
after this commit.

## Fixture

`SEMANTIC_ENTITY_SWAP` is constructed from `SEMANTIC_ORIGINAL` by cyclic
permutation of subjects across the ten facts:

| original | entity swap |
|---|---|
| "Maya lives in Berlin." | "Omar lives in Berlin." |
| "Omar works as a teacher." | "Priya works as a teacher." |
| "Priya owns a red bicycle." | "Noah owns a red bicycle." |
| "Noah visits his grandmother every Sunday." | "Elena visits his grandmother every Sunday." |
| "Elena prefers tea in the morning." | "Victor prefers tea in the morning." |
| "Victor repaired the broken window." | "Sara repaired the broken window." |
| "Sara speaks French at home." | "Daniel speaks French at home." |
| "Daniel adopted a small dog." | "Iris adopted a small dog." |
| "Iris paid the electricity bill yesterday." | "Leo paid the electricity bill yesterday." |
| "Leo studies mathematics at university." | "Maya studies mathematics at university." |

Each fact becomes false (attributes a different person's action to someone
else), but the corpus vocabulary is unchanged: every word that appears in the
swap set also appears in the original set.

## Criterion

`paraphrase` must be strictly less divergent than `entity_swap` at thresholds
0.72 and 0.82. This is the same comparison form used in the existing antonym
check.

## Rationale

Bi-encoder sentence-embedding models treat sentences as approximately
commutative bags of words and are known to poorly distinguish structural
near-matches such as "the dog bit the man" vs "the man bit the dog"
(Yuksekgonul et al., 2022; see also arXiv 2604.16351). An entity swap changes
one token out of five to seven, which may be below the model's discrimination
threshold.

## Predictions

**Prediction A (primary).** The criterion will fail at 0.60 and 0.72 --
entity_swap will be weakly distinguishable from the original, because replacing
one name out of five-to-seven tokens changes the embedding by less than the
cosine threshold. This would represent a real discrimination defect of the
metric at those thresholds.

**Prediction B (counter).** MiniLM is contrastively fine-tuned on NLI/STS data,
which may provide entity sensitivity that generic bag-of-words models lack. The
criterion will pass at 0.72 and 0.82.

## Frozen reference

| item | value |
|---|---|
| `validate_symdiff_probe.py` SHA-256 at registration | `3963c7c73d10786b9e1fd548e51d8fd96085af36210b6b2ad68bfa54eaa4fa3b` |
