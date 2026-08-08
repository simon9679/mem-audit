"""Zero-quota analysis of the 2.0.17 H2/I2 pair (same method as analyze_hi.py,
ported to the 2.x search signature: filters + top_k). Produces H2<->I2 symdiff,
H2<->H2 control, prefix curve, retrieval on the 20 frozen questions, amplification.
Paths from env (MEM0_2X_OUT). search() is embed-only -> zero LLM."""
import json, os, statistics
os.environ.setdefault("MEM0_TELEMETRY", "False")
import numpy as np
from sentence_transformers import SentenceTransformer
from mem0 import Memory

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("MEM0_2X_OUT", "./mem0_2x")
QF = os.path.join(HERE, "retrieval_questions.json")
ST = SentenceTransformer("all-MiniLM-L6-v2")
THRESHOLDS = (0.60, 0.72, 0.82)


def emb(t): return ST.encode(list(t), normalize_embeddings=True) if t else np.zeros((0, 384))


def _stats(na, nb, m):
    u = na + nb - m; sd = na + nb - 2 * m
    return {"A": na, "B": nb, "AmB": na - m, "BmA": nb - m,
            "symdiff_pct": round(100 * sd / u, 2) if u else 0.0, "jaccard": round(m / u, 4) if u else 0.0}


def greedy_symdiff(a, b):
    from collections import Counter
    out = {}; cb = Counter(b); m = 0
    for s in a:
        if cb.get(s, 0) > 0: cb[s] -= 1; m += 1
    out["exact"] = _stats(len(a), len(b), m)
    sim = emb(a) @ emb(b).T if (a and b) else None
    for t in THRESHOLDS:
        m = 0
        if sim is not None:
            idx = np.argwhere(sim >= t)
            order = np.argsort(-sim[idx[:, 0], idx[:, 1]], kind="stable") if idx.size else []
            ua, ub = set(), set()
            for k in order:
                i, j = int(idx[k, 0]), int(idx[k, 1])
                if i in ua or j in ub: continue
                ua.add(i); ub.add(j); m += 1
        out[f"{t:.2f}"] = _stats(len(a), len(b), m)
    return out


def load_facts(label): return json.load(open(os.path.join(OUT, f"dump_{label}_p8.json"), encoding="utf-8"))["facts"]


def cfg(cdir, coll):
    return {"vector_store": {"provider": "chroma", "config": {"collection_name": coll, "path": cdir}},
            "embedder": {"provider": "huggingface", "config": {"model": "sentence-transformers/all-MiniLM-L6-v2"}},
            "llm": {"provider": "litellm", "config": {"model": "cerebras/gpt-oss-120b", "temperature": 0}}}


def retrieve(cdir, coll, uid, qs):
    m = Memory.from_config(cfg(cdir, coll)); out = []
    for q in qs:
        r = m.search(q, filters={"user_id": uid}, top_k=5)   # 2.x signature
        it = r.get("results", r) if isinstance(r, dict) else r
        out.append([x.get("memory") or x.get("text") or "" for x in it])
    return out


def main():
    H = load_facts("H2"); I = load_facts("I2")
    res = {"HI_full": greedy_symdiff([f["text"] for f in H], [f["text"] for f in I]),
           "HH_control": greedy_symdiff([f["text"] for f in H], [f["text"] for f in H]), "prefix": {}}
    for hi in (4, 9, 16, 24, 32):
        hf = [f["text"] for f in H if f["session_idx"] is not None and f["session_idx"] <= hi]
        gf = [f["text"] for f in I if f["session_idx"] is not None and f["session_idx"] <= hi]
        res["prefix"][f"0-{hi}"] = {"nH": len(hf), "nI": len(gf), **greedy_symdiff(hf, gf)["0.72"]}
    qs = json.load(open(QF, encoding="utf-8"))
    Hq = retrieve(os.path.join(OUT, "chroma_H2"), "col_p8_H2", "p8_run_H2", qs)
    Iq = retrieve(os.path.join(OUT, "chroma_I2"), "col_p8_I2", "p8_run_I2", qs)
    poolH = sorted({x for f in Hq for x in f}); poolI = sorted({x for f in Iq for x in f})
    res["retrieval_pooled"] = greedy_symdiff(poolH, poolI)
    ov = [len(set(a) & set(b)) / len(set(a) | set(b)) if (set(a) | set(b)) else 1.0 for a, b in zip(Hq, Iq)]
    res["retrieval_perq_jaccard_mean"] = round(statistics.mean(ov), 3)
    res["retrieval_perq_identical"] = sum(1 for j in ov if j == 1.0)
    mc, dc = [], []
    for q, af, bf in zip(qs, Hq, Iq):
        qv = emb([q])[0]; av = emb(af); bv = emb(bf); ma, mb = set(), set()
        if len(af) and len(bf):
            sim = av @ bv.T
            for s, i, j in sorted([(sim[i, j], i, j) for i in range(len(af)) for j in range(len(bf)) if sim[i, j] >= 0.72], reverse=True):
                if i in ma or j in mb: continue
                ma.add(i); mb.add(j)
        for i in range(len(af)): (mc if i in ma else dc).append(float(qv @ av[i]))
        for j in range(len(bf)): (mc if j in mb else dc).append(float(qv @ bv[j]))
    res["amplification"] = {"matched_n": len(mc), "diverging_n": len(dc),
                            "cos_matched": round(statistics.mean(mc), 3) if mc else None,
                            "cos_diverging": round(statistics.mean(dc), 3) if dc else None}
    json.dump(res, open(os.path.join(OUT, "analysis_H2I2.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
