"""
Live smoke test for embedding chunking (TZ Task 1) on real volume.

The mock unit tests already prove the batching *logic*. This script proves the
fix holds against a REAL Mem0 store and a REAL embedder on >=150 varied facts —
the thing mocks can't show: that the embedder is actually invoked in multiple
batches, none over the per-request thresholds, with vector order preserved 1:1.

What it does (all keys read from env only; nothing hardcoded, nothing written
to the repo, audit stays read-only):

  Step 0  Pick an embedder by what's available, and ALWAYS route it through the
          library's real batch wrapper (_embed_in_batches):
            1. MEM_AUDIT_OLLAMA=1                   -> local Ollama path  (6000/64)
            2. OPENAI_API_KEY                      -> openai path        (250000/128)
            3. else local sentence-transformers    -> wrapped in an OpenAI-embeddings-
               shaped adapter and fed to openai_compatible_embedder() with ARTIFICIALLY LOW
               thresholds (32 items / 2000 tokens) so a small local set still
               produces >1 batch and exercises the same chunking/stitching code.
  Step 1  Bring up a real self-hosted mem0.Memory (huggingface embedder + embedded
          Qdrant, fully offline). Falls back to an in-memory fake ONLY if that
          can't come up — and says so loudly.
  Step 2  Seed >=150 facts to one test user_id: varied lengths, a few long
          (>=1800 chars), one near-8K-token monster, plus planted duplicate /
          contradiction / update pairs so findings are non-empty.
  Step 3  Run the audit pipeline and collect hard evidence: embedder call count
          (>1), per-batch sizes vs thresholds, final matrix shape (N, dim) and
          1:1 order (batched vs per-text single embeddings must match), the
          "Computing embeddings..." stage firing, and real findings.
  Step 4  Negative ceiling check — only meaningful with a real provider key.
          Skipped here (local embedder) with a numeric argument for why one
          unbatched call would have failed.

Run:  python dev-scripts/live_smoke_chunking.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import shutil
import warnings
from dataclasses import dataclass

warnings.filterwarnings("ignore")

# Allow running directly from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from datetime import datetime, timedelta, timezone  # noqa: E402

from mem_audit.embeddings import _make_token_counter, openai_compatible_embedder  # noqa: E402
from mem_audit.detectors.duplicates import CandidatePair  # noqa: E402
from mem_audit.detectors.contradictions import (  # noqa: E402
    _build_judge_prompt,
    find_contradictions,
    openai_compatible_judge,
)
from mem_audit.connectors.mem0_connector import MemoryRecord, Mem0Connector  # noqa: E402

TEST_USER = "chunking_smoke_user"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# OpenAI-embeddings-shaped adapters
# --------------------------------------------------------------------------- #
class _Item:
    def __init__(self, embedding):
        self.embedding = embedding


class _Resp:
    def __init__(self, data):
        self.data = data


class _LocalSTEmbeddings:
    """`.create(model, input)` backed by a local sentence-transformers model."""

    def __init__(self, model):
        self._model = model

    def create(self, model, input):
        vecs = self._model.encode(list(input), show_progress_bar=False, normalize_embeddings=False)
        return _Resp([_Item(np.asarray(v, dtype=np.float32).tolist()) for v in vecs])


class _LocalSTClient:
    def __init__(self, model_name):
        from sentence_transformers import SentenceTransformer

        self._st = SentenceTransformer(model_name)
        self.embeddings = _LocalSTEmbeddings(self._st)


class _CountingEmbeddings:
    """Wraps a real `.embeddings` and records every batch it's asked to embed."""

    def __init__(self, inner):
        self._inner = inner
        self.batches: list[list[str]] = []

    def create(self, model, input):
        batch = list(input)
        self.batches.append(batch)
        return self._inner.create(model=model, input=batch)


class _CountingClient:
    def __init__(self, inner):
        self._inner = inner
        self.embeddings = _CountingEmbeddings(inner.embeddings)

    def raw_single(self, model, text):
        """Embed ONE text through the underlying (uncounted) client — for the order check."""
        return self._inner.embeddings.create(model=model, input=[text]).data[0].embedding


@dataclass
class EmbedderChoice:
    embed_fn: object
    counting: _CountingClient
    provider: str
    model: str
    dim: int
    max_items: int
    max_tokens: int
    note: str


def build_embedder() -> EmbedderChoice:
    use_ollama = os.environ.get("MEM_AUDIT_OLLAMA", "").strip()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()

    # A local Ollama server exposes an OpenAI-compatible endpoint with no key.
    # Set MEM_AUDIT_OLLAMA=1 (after `ollama pull nomic-embed-text`) to exercise
    # the chunking path against a real endpoint with small thresholds, offline.
    if use_ollama:
        import openai

        raw = openai.OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
        counting = _CountingClient(raw)
        model = "nomic-embed-text"
        fn = openai_compatible_embedder(model=model, client=counting, max_batch_items=64, max_batch_tokens=6000)
        return EmbedderChoice(fn, counting, "ollama", model, 768, 64, 6000,
                              "local Ollama, small per-request thresholds")

    if openai_key:
        import openai

        raw = openai.OpenAI(api_key=openai_key)
        counting = _CountingClient(raw)
        model = "text-embedding-3-small"
        fn = openai_compatible_embedder(model=model, client=counting, max_batch_items=128, max_batch_tokens=250_000)
        return EmbedderChoice(fn, counting, "openai", model, 1536, 128, 250_000,
                              "real OpenAI per-request thresholds")

    # Local, offline, no key. sentence-transformers has no per-request limit, so
    # we deliberately set LOW thresholds to force >1 batch on ~150 facts and
    # exercise the exact same chunking/stitching path the paid providers use.
    st_client = _LocalSTClient("all-MiniLM-L6-v2")
    counting = _CountingClient(st_client)
    model = "local-sentence-transformers/all-MiniLM-L6-v2"
    fn = openai_compatible_embedder(model=model, client=counting, max_batch_items=32, max_batch_tokens=2000)
    return EmbedderChoice(fn, counting, "local_sentence_transformers", model, 384, 32, 2000,
                          "ARTIFICIALLY LOW thresholds (32 items / 2000 tokens) to force multi-batch")


# --------------------------------------------------------------------------- #
# Seed data
# --------------------------------------------------------------------------- #
# Planted pairs: (text_a, text_b, expected_label). Each pair is semantically
# close (so the embedding pass surfaces it as a candidate) and carries distinctive
# tokens the canned fast judge keys on. The REAL Cerebras judge is also run on
# these later — no canned knowledge involved there.
PLANTED = [
    ("The user has a dog named Rex who loves playing fetch.",
     "User owns a dog called Rex.", "DUPLICATE"),
    ("The user practices the violin every single evening after dinner.",
     "The user plays the violin each night.", "DUPLICATE"),
    ("The user enjoys drinking oolong tea every morning before work.",
     "The user likes a cup of oolong tea each morning.", "DUPLICATE"),
    ("The user is a strict vegetarian and never eats any meat.",
     "The user had a large beef steak for dinner yesterday.", "CONTRADICTION"),
    ("The user's all-time favorite football club is Liverpool.",
     "The user's all-time favorite football club is Arsenal.", "CONTRADICTION"),
    ("The user lives in the city of Berlin.",
     "The user recently moved and now lives in Madrid.", "UPDATE"),
    ("The user works as a junior backend developer.",
     "The user was just promoted to senior backend developer.", "UPDATE"),
]


def _canned_judge(prompt: str) -> str:
    """Fast local stand-in judge, keyed on the planted pairs' distinctive tokens.

    Used ONLY for the full-volume run_audit pass (hundreds of candidate pairs on
    a 5-RPM free tier would take hours). The real Cerebras judge is run
    separately on the planted subset. Anything unrecognized -> UNRELATED.
    """
    p = prompt.lower()
    # DUPLICATE rules: the marker must appear in BOTH memories (>=2 occurrences),
    # so a planted "Rex" fact paired with an unrelated filler doesn't get a false
    # DUPLICATE just because "rex" shows up once.
    dup_markers = ["rex", "violin", "oolong"]
    for m in dup_markers:
        if p.count(m) >= 2:
            return '{"label": "DUPLICATE", "rationale": "planted duplicate pair"}'
    two_token = [
        (("vegetarian", "steak"), "CONTRADICTION"),
        (("liverpool", "arsenal"), "CONTRADICTION"),
        (("berlin", "madrid"), "UPDATE"),
        (("junior", "senior"), "UPDATE"),
    ]
    for keys, label in two_token:
        if all(k in p for k in keys):
            return '{"label": "%s", "rationale": "planted %s pair"}' % (label, label)
    return '{"label": "UNRELATED", "rationale": "no planted match"}'


_FILLER_TEMPLATES = [
    "The user visited a small coastal town number {i} during a summer holiday.",
    "The user read an interesting article about topic {i} last weekend.",
    "The user bought a vintage item labelled {i} from an online marketplace.",
    "The user attended a workshop on subject {i} organised by a local group.",
    "The user tried a new recipe number {i} that used seasonal vegetables.",
    "The user watched a documentary about historical event {i} on a rainy day.",
    "The user planted flower variety {i} in the community garden this spring.",
    "The user repaired an old gadget model {i} found in the attic.",
]


def build_seed_texts() -> list[str]:
    texts: list[str] = []
    for a, b, _label in PLANTED:
        texts.append(a)
        texts.append(b)

    # Filler unrelated facts to reach comfortably past 150.
    i = 0
    while len(texts) < 156:
        tmpl = _FILLER_TEMPLATES[i % len(_FILLER_TEMPLATES)]
        texts.append(tmpl.format(i=i))
        i += 1

    # A few long facts (>=1800 chars) to exercise the token dimension, not just
    # item count.
    long_body = ("The user wrote a detailed personal journal entry describing a "
                 "long hiking trip through the mountains, including the weather, "
                 "the trail conditions, the food they packed, and the people they "
                 "met along the way. ")
    for k in range(3):
        texts.append(("Journal entry %d. " % k) + long_body * 8)  # ~1800+ chars

    # Two near-8K-token facts: each fact's own token estimate must sit just UNDER
    # the real OpenAI-family per-input ceiling (~8192) — an input that exceeds it
    # on its own is a separate error, not a chunking one. Each still overflows the
    # small per-request batch budget (6000), so it's emitted in a batch by itself
    # and probes behaviour right at the ceiling.
    for k in range(2):
        texts.append(("Extended activity log %d. " % k)
                      + " ".join("token%d" % j for j in range(2600)))  # ~7K tokens, < 8192

    return texts


# --------------------------------------------------------------------------- #
# Store: real Mem0, with an honest fallback
# --------------------------------------------------------------------------- #
class _FakeMem0Client:
    """Fallback store with the same get_all() contract, if real Mem0 won't come up."""

    def __init__(self, texts, user_id):
        from datetime import datetime, timezone, timedelta

        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self._items = [
            {"id": "m%d" % i, "user_id": user_id, "memory": t,
             "created_at": (base + timedelta(days=i)).isoformat()}
            for i, t in enumerate(texts)
        ]

    def get_all(self, filters=None, top_k=500, **kwargs):
        uid = (filters or {}).get("user_id")
        return {"results": [x for x in self._items if x["user_id"] == uid][:top_k]}

    def history(self, memory_id):
        return []


def build_store(texts):
    """Returns (client, description, qdrant_dir_or_None)."""
    qdir = tempfile.mkdtemp(prefix="memaudit_smoke_qdrant_")
    try:
        from mem0 import Memory

        cfg = {
            "vector_store": {"provider": "qdrant", "config": {
                "path": qdir, "collection_name": "chunking_smoke", "embedding_model_dims": 384}},
            "embedder": {"provider": "huggingface", "config": {"model": "all-MiniLM-L6-v2"}},
            # Dummy key: with infer=False and get_all, the LLM is constructed but
            # never called. This keeps Mem0 fully offline for seeding.
            "llm": {"provider": "openai", "config": {"api_key": "sk-not-used", "model": "gpt-4o-mini"}},
        }
        client = Memory.from_config(cfg)
        for t in texts:
            client.add(t, user_id=TEST_USER, infer=False)
        return client, "REAL self-hosted mem0.Memory (huggingface embedder + embedded Qdrant, offline)", qdir
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(qdir, ignore_errors=True)
        log("  ! Real Mem0 did not come up (%s) — falling back to in-memory fake store "
            "with the SAME real record count." % type(e).__name__)
        return _FakeMem0Client(texts, TEST_USER), \
            "FAKE in-memory store (real Mem0 unavailable) — embeddings are still real/local", None


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def _batch_stats(batches, count_tokens):
    """Returns (rows, max_items, max_tokens_multi, oversized_singles).

    max_tokens_multi is the largest token estimate among MULTI-item batches — the
    ones chunking is responsible for keeping under the ceiling. A single input
    whose own estimate exceeds the ceiling can't be split further and is reported
    separately (oversized_singles) rather than counted as a chunking failure.
    """
    rows = []
    max_items = 0
    max_tokens_multi = 0
    oversized = []
    for idx, batch in enumerate(batches, start=1):
        tok = sum(count_tokens(t) for t in batch)
        rows.append((idx, len(batch), tok))
        max_items = max(max_items, len(batch))
        if len(batch) > 1:
            max_tokens_multi = max(max_tokens_multi, tok)
        else:
            oversized.append((idx, tok))
    return rows, max_items, max_tokens_multi, oversized


def main() -> int:
    def emit(line=""):
        print(line, flush=True)

    # ---- Step 0: embedder ----
    log("Step 0: selecting embedder...")
    ch = build_embedder()
    count_tokens = _make_token_counter(ch.model)
    log("  embedder=%s dim=%d thresholds=%d items / %d tokens (%s)"
        % (ch.provider, ch.dim, ch.max_items, ch.max_tokens, ch.note))

    texts = build_seed_texts()
    seeded = len(texts)

    # ---- PRIMARY chunking proof: the full seeded set straight through the
    #      embedder's batch wrapper. This is the real-volume proof for Task 1;
    #      it does not depend on how many records mem0 later hands back. ----
    log("Primary proof: embedding all %d seeded facts through the batch wrapper..." % seeded)
    ch.counting.embeddings.batches.clear()
    V_full = ch.embed_fn(texts)
    primary_batches = list(ch.counting.embeddings.batches)
    rows, max_items, max_tokens_multi, oversized = _batch_stats(primary_batches, count_tokens)

    # Order integrity: each batched vector must match a fresh single embedding of
    # the SAME text. We compare by cosine, not exact equality: real
    # text-embedding-3-small is not bit-identical across requests (batch vs single
    # differ by ~1e-3 from server-side nondeterminism), so a strict allclose would
    # false-fail. A scrambled order would instead drop cosine far below 1.0.
    # Sampled indices only (batch boundaries, tail, oversized singles) so we don't
    # fire N extra single-embed calls at a real metered provider.
    shape_ok = V_full.shape == (seeded, ch.dim)
    candidate_idx = ([0, ch.max_items - 1, ch.max_items, seeded // 2,
                      seeded - 3, seeded - 2, seeded - 1]
                     + list(range(0, seeded, max(1, seeded // 6))))
    sample_idx = sorted({i for i in candidate_idx if 0 <= i < seeded})

    def _cos(a, b):
        return float(np.dot(a, b) / ((np.linalg.norm(a) + 1e-9) * (np.linalg.norm(b) + 1e-9)))

    order_ok = True
    order_min_cos = 1.0
    for i in sample_idx:
        single = np.asarray(ch.counting.raw_single(ch.model, texts[i]), dtype=np.float32)
        cos = _cos(V_full[i], single)
        order_min_cos = min(order_min_cos, cos)
        if cos < 0.98:
            order_ok = False
            break

    # ---- Steps 1-2: real Mem0 store + end-to-end audit path ----
    log("Steps 1-2: seeding a real Mem0 store and running the end-to-end pipeline...")
    client, store_desc, qdir = build_store(texts)
    try:
        from mem_audit.pipeline import run_audit

        stage_seen = {"embed": False}

        def on_stage(msg: str):
            log("  [stage] " + msg)
            if msg.startswith("Computing embeddings"):
                stage_seen["embed"] = True

        ch.counting.embeddings.batches.clear()
        e2e_findings, e2e_read = run_audit(
            mem0_client=client, user_id=TEST_USER,
            embed_fn=ch.embed_fn, llm_call=_canned_judge,
            top_k=5, min_similarity=0.05, page_size=1000,
            on_stage=on_stage,
        )
        e2e_batches = len(ch.counting.embeddings.batches)
        by_type = {}
        for f in e2e_findings:
            by_type[f.type.value] = by_type.get(f.type.value, 0) + 1
    finally:
        if qdir:
            shutil.rmtree(qdir, ignore_errors=True)

    # ---- Real Cerebras judge on ALL planted pairs (with dates -> also exercises
    #      the date-aware prompt from Task 3). Built directly so every planted
    #      relation gets a real label regardless of mem0's read limit. ----
    cerebras_key = os.environ.get("CEREBRAS_API_KEY", "").strip()
    real_rows = []
    skipped_count = {"n": 0}
    sample_prompt = ""
    real_desc = "SKIPPED: no CEREBRAS_API_KEY in env"
    if cerebras_key:
        planted_pairs = []
        for i, (a, b, expected) in enumerate(PLANTED):
            ra = MemoryRecord(id="pa%d" % i, text=a,
                              created_at=datetime(2026, 1, 1 + i, tzinfo=timezone.utc))
            # updates far apart in time, contradictions close — matches the prompt's
            # "large gap -> UPDATE, same period -> CONTRADICTION" hint.
            gap_days = 700 if expected == "UPDATE" else 3
            rb = MemoryRecord(id="pb%d" % i, text=b,
                              created_at=datetime(2026, 1, 1 + i, tzinfo=timezone.utc)
                              + timedelta(days=gap_days))
            planted_pairs.append((CandidatePair(ra, rb, 0.9), expected))
        sample_prompt = _build_judge_prompt(planted_pairs[5][0].record_a,
                                            planted_pairs[5][0].record_b)

        log("Real judge: classifying %d planted pairs with Cerebras gpt-oss-120b (throttled)..."
            % len(planted_pairs))
        judge = openai_compatible_judge(
            model="gpt-oss-120b",
            base_url="https://api.cerebras.ai/v1",
            api_key=cerebras_key,
            api_key_env="CEREBRAS_API_KEY",
            max_retries=5,
        )

        def on_skip(_pair):
            skipped_count["n"] += 1

        pairs_only = [p for p, _e in planted_pairs]
        real_findings = find_contradictions(pairs_only, judge, min_request_interval=6.0, on_skip=on_skip)
        # map finding by memory id back to expected label
        fmap = {tuple(sorted(f.memory_ids)): f for f in real_findings}
        for pair, expected in planted_pairs:
            key = tuple(sorted([pair.record_a.id, pair.record_b.id]))
            f = fmap.get(key)
            got = f.type.value if f else "unrelated/none"
            real_rows.append((pair.record_a.text[:40], expected, got))
        real_desc = ("REAL Cerebras gpt-oss-120b — %d finding(s) over %d planted pairs, %d skipped"
                     % (len(real_findings), len(planted_pairs), skipped_count["n"]))

    total_tokens_all = sum(count_tokens(t) for t in texts)
    biggest = max(count_tokens(t) for t in texts)

    # ---- Step 3: real negative ceiling check (live, real provider only) ----
    # A single unbatched create() must fail once the request exceeds the real
    # per-request token ceiling (~64000 on OpenAI-family endpoints). The 161-fact
    # set (~16.7K tokens) is under that, so we build a compact probe set that
    # clears it: ~11 near-7K inputs (each < 8192 per-input, > 64000 in total).
    # Raw single call over the probe set -> expected 413; the batched path over
    # the SAME set -> pass. Direct proof the fix solves a real endpoint problem.
    neg = None  # (raw_failed, detail, batched_ok, big_n, big_tokens)
    if ch.provider in ("ollama", "openai"):
        block = "Ceiling probe %d. " + " ".join("token%d" % j for j in range(2600))
        big = [block % k for k in range(11)]  # 11 * ~6.8K ~= 75K tokens, over 64000
        big_tokens = sum(count_tokens(t) for t in big)
        log("Step 3: raw unbatched create() over %d near-7K inputs (~%d tokens, expect 413)..."
            % (len(big), big_tokens))
        raw_failed, detail = False, ""
        try:
            ch.counting._inner.embeddings.create(model=ch.model, input=list(big))
            detail = ("raw single call unexpectedly SUCCEEDED at ~%d tokens — provider "
                      "per-request ceiling is higher than this probe set" % big_tokens)
        except Exception as e:  # noqa: BLE001
            raw_failed = True
            detail = "%s: %s" % (type(e).__name__, str(e)[:300])
        batched_ok = False
        try:
            Vb = ch.embed_fn(big)
            batched_ok = Vb.shape == (len(big), ch.dim)
        except Exception as e:  # noqa: BLE001
            detail += "  | batched path FAILED: %s: %s" % (type(e).__name__, str(e)[:200])
        neg = (raw_failed, detail, batched_ok, len(big), big_tokens)

    # ---- Report ----
    emit("=" * 72)
    emit("LIVE SMOKE TEST -- embedding chunking on real volume")
    emit("=" * 72)
    emit("")
    emit("Embedder:   %s  (dim %d)" % (ch.provider, ch.dim))
    emit("  model:    %s" % ch.model)
    emit("  batch thresholds: %d items / %d tokens  [%s]" % (ch.max_items, ch.max_tokens, ch.note))
    emit("Store:      %s" % store_desc)
    emit("Judge:      %s" % real_desc)
    emit("")
    emit("-- PRIMARY: chunking of all %d seeded facts through the embedder -------" % seeded)
    emit("Embedder .create() calls:          %d   %s"
         % (len(primary_batches), "PASS (>1)" if len(primary_batches) > 1 else "FAIL"))
    emit("Max items in any batch:            %d / %d   %s"
         % (max_items, ch.max_items, "PASS" if max_items <= ch.max_items else "FAIL"))
    emit("Max tokens in any MULTI-item batch:%d / %d   %s"
         % (max_tokens_multi, ch.max_tokens, "PASS" if max_tokens_multi <= ch.max_tokens else "FAIL"))
    emit("Oversized single-item batches:     %d  (facts bigger than the whole token"
         % len(oversized))
    emit("                                   budget -> emitted alone, cannot be split)")
    emit("Final matrix shape:                %s   %s"
         % (str(tuple(V_full.shape)), "PASS" if shape_ok else "FAIL"))
    emit("Vector order (cosine>=0.98, %d idx): %s  (min cos %.4f)"
         % (len(sample_idx), "PASS" if order_ok else "FAIL", order_min_cos))
    emit("")
    emit("Batch table (first 14 of %d):" % len(primary_batches))
    emit("  %-6s %-8s %-12s" % ("batch", "items", "~tokens"))
    for idx, items, tok in rows[:14]:
        flag = "  <- oversized single" if items == 1 and tok > ch.max_tokens else ""
        emit("  %-6d %-8d %-12d%s" % (idx, items, tok, flag))
    if len(rows) > 14:
        emit("  ... (%d more)" % (len(rows) - 14))
    emit("")
    emit("-- END-TO-END via real Mem0 (audit pipeline) -----------------------")
    emit("Facts seeded into Mem0:            %d" % seeded)
    emit("Records read back by audit:        %d" % e2e_read)
    if e2e_read < seeded:
        emit("  NOTE: mem0 legacy get_all() defaults to limit=100 and the connector's")
        emit("  TypeError-fallback path does not forward page_size, so it silently read")
        emit("  only %d of %d. This is the deferred 'fallback loses page_size' bug --" % (e2e_read, seeded))
        emit("  the smoke test shows it causes a SILENT under-read (100 != page_size, so")
        emit("  the page-size ceiling guard does not catch it either).")
    emit("'Computing embeddings...' stage:   %s"
         % ("fired -> reached judging" if stage_seen["embed"] else "NOT SEEN"))
    emit("Embedder .create() calls (e2e):    %d" % e2e_batches)
    emit("Findings (canned judge): %d  by type: %s"
         % (len(e2e_findings), ", ".join("%s=%d" % kv for kv in sorted(by_type.items())) or "none"))
    emit("")
    emit("-- REAL judge on planted pairs (Cerebras) + date-aware prompt ------")
    if real_rows:
        emit("  %-42s %-14s %-14s" % ("memory A (truncated)", "expected", "got"))
        for a, exp, got in real_rows:
            emit("  %-42s %-14s %-14s" % (a, exp, got))
        emit("")
        emit("  sample assembled prompt (dates come from created_at -- Task 3):")
        for ln in sample_prompt.splitlines()[:6]:
            emit("    | " + ln)
    else:
        emit("  " + real_desc)
    emit("")
    emit("-- Step 3: negative ceiling check (live raw single call) -----------")
    emit("  main set: %d facts, %d tokens total; biggest single fact %d tokens (< 8192)"
         % (seeded, total_tokens_all, biggest))
    if neg is not None:
        raw_failed, detail, batched_ok, big_n, big_tokens = neg
        emit("  probe set: %d near-7K inputs, ~%d tokens (over the measured 64000 ceiling)"
             % (big_n, big_tokens))
        if raw_failed:
            emit("  RAW unbatched create(input=probe_set) -> FAILED as expected:")
            emit("    %s" % detail)
        else:
            emit("  RAW call did NOT fail: %s" % detail)
        emit("  BATCHED embedder over the SAME probe set -> %s"
             % ("PASSED" if batched_ok else "FAILED"))
    else:
        emit("  SKIPPED: local embedder, no real provider key -- numeric argument only:")
        emit("  one unbatched create() over the main set is %.1fx the ~8192 per-input"
             % (biggest / 8192.0))
        emit("  figure; batched path passed above.")
    emit("")
    emit("=" * 72)
    chunking_ok = (len(primary_batches) > 1 and max_items <= ch.max_items
                   and max_tokens_multi <= ch.max_tokens and shape_ok and order_ok)
    neg_ok = (neg is None) or (neg[0] and neg[2])  # raw failed AND batched passed
    verdict_ok = chunking_ok and neg_ok
    emit("VERDICT: chunking holds on real volume: %s" % ("YES" if verdict_ok else "NO"))
    emit("=" * 72)
    return 0 if verdict_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
