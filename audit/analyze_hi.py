"""
Zero-quota final analysis of the resumable H/I runs. Produces:
  - H vs I full symdiff (4 thresholds) + H vs H control (must be 0)
  - prefix curve: symdiff on sessions 0-4, 0-9, 0-16, 0-24, 0-32
  - retrieval on the 20 frozen questions (search top-5 on H and I stores), symdiff
  - amplification: mean cosine(question, matched fact) vs (question, diverging fact)
Writes analysis_HI.json and prints a summary. search() is embed-only (zero LLM).
"""
import json, os, statistics
os.environ.setdefault("MEM0_TELEMETRY", "False")
import numpy as np
from sentence_transformers import SentenceTransformer
from mem0 import Memory

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("MEM0_RESUME_DIR", "./mem0_resume")  # local run dir, outside the repo
QF = os.path.join(HERE, "retrieval_questions.json")
ST = SentenceTransformer("all-MiniLM-L6-v2")
THRESHOLDS = (0.60, 0.72, 0.82)


def emb(texts):
    return ST.encode(list(texts), normalize_embeddings=True) if texts else np.zeros((0, 384))


def greedy_symdiff(a, b):
    """Same metric as symdiff_probe: exact + greedy 1-1 cosine at each threshold."""
    na, nb = len(a), len(b)
    out = {}
    # exact
    from collections import Counter
    cb = Counter(b); m = 0
    for s in a:
        if cb.get(s, 0) > 0: cb[s] -= 1; m += 1
    out["exact"] = _stats(na, nb, m)
    if na and nb:
        sim = emb(a) @ emb(b).T
    for t in THRESHOLDS:
        m = 0
        if na and nb:
            idx = np.argwhere(sim >= t)
            order = np.argsort(-sim[idx[:, 0], idx[:, 1]], kind="stable") if idx.size else []
            ua, ub = set(), set()
            for k in order:
                i, j = int(idx[k, 0]), int(idx[k, 1])
                if i in ua or j in ub: continue
                ua.add(i); ub.add(j); m += 1
        out[f"{t:.2f}"] = _stats(na, nb, m)
    return out


def _stats(na, nb, m):
    u = na + nb - m; sd = na + nb - 2 * m
    return {"A": na, "B": nb, "AmB": na - m, "BmA": nb - m,
            "symdiff_pct": round(100 * sd / u, 2) if u else 0.0,
            "jaccard": round(m / u, 4) if u else 0.0}


def load_facts(label):
    d = json.load(open(os.path.join(OUT, f"dump_{label}_p8.json"), encoding="utf-8"))
    return d["facts"]


def cfg(cdir, coll):
    return {"vector_store": {"provider": "chroma", "config": {"collection_name": coll, "path": cdir}},
            "embedder": {"provider": "huggingface", "config": {"model": "sentence-transformers/all-MiniLM-L6-v2"}},
            "llm": {"provider": "litellm", "config": {"model": "cerebras/gpt-oss-120b", "temperature": 0}}}


def retrieve(cdir, coll, uid, questions):
    m = Memory.from_config(cfg(cdir, coll))
    per_q = []
    for q in questions:
        r = m.search(q, user_id=uid, limit=5, rerank=False)
        it = r.get("results", r) if isinstance(r, dict) else r
        per_q.append([x.get("memory") or x.get("text") or "" for x in it])
    return per_q


def main():
    H = load_facts("H"); I = load_facts("I")
    res = {}
    ht = [f["text"] for f in H]; it_ = [f["text"] for f in I]
    res["HI_full"] = greedy_symdiff(ht, it_)
    res["HH_control"] = greedy_symdiff(ht, ht)

    # prefix curve
    res["prefix"] = {}
    for hi in (4, 9, 16, 24, 32):
        hf = [f["text"] for f in H if f["session_idx"] is not None and f["session_idx"] <= hi]
        gf = [f["text"] for f in I if f["session_idx"] is not None and f["session_idx"] <= hi]
        res["prefix"][f"0-{hi}"] = {"nH": len(hf), "nI": len(gf), **greedy_symdiff(hf, gf)["0.72"]}

    # retrieval
    qs = json.load(open(QF, encoding="utf-8"))
    Hq = retrieve(os.path.join(OUT, "chroma_H"), "col_p8_H", "p8_run_H", qs)
    Iq = retrieve(os.path.join(OUT, "chroma_I"), "col_p8_I", "p8_run_I", qs)
    poolH = sorted({x for f in Hq for x in f}); poolI = sorted({x for f in Iq for x in f})
    res["retrieval_pooled"] = greedy_symdiff(poolH, poolI)
    ov = []
    for a, b in zip(Hq, Iq):
        sa, sb = set(a), set(b); ov.append(len(sa & sb) / len(sa | sb) if (sa | sb) else 1.0)
    res["retrieval_perq_jaccard_mean"] = round(statistics.mean(ov), 3)
    res["retrieval_perq_identical"] = sum(1 for j in ov if j == 1.0)

    # amplification
    mc, dc = [], []
    for q, af, bf in zip(qs, Hq, Iq):
        qv = emb([q])[0]; av = emb(af); bv = emb(bf); ma, mb = set(), set()
        if len(af) and len(bf):
            sim = av @ bv.T
            pairs = sorted([(sim[i, j], i, j) for i in range(len(af)) for j in range(len(bf)) if sim[i, j] >= 0.72], reverse=True)
            ua, ub = set(), set()
            for s, i, j in pairs:
                if i in ua or j in ub: continue
                ua.add(i); ub.add(j); ma.add(i); mb.add(j)
        for i in range(len(af)): (mc if i in ma else dc).append(float(qv @ av[i]))
        for j in range(len(bf)): (mc if j in mb else dc).append(float(qv @ bv[j]))
    res["amplification"] = {"matched_n": len(mc), "diverging_n": len(dc),
                            "cos_matched": round(statistics.mean(mc), 3) if mc else None,
                            "cos_diverging": round(statistics.mean(dc), 3) if dc else None}

    json.dump(res, open(os.path.join(OUT, "analysis_HI.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
