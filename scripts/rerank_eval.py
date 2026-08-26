#!/usr/bin/env python3
"""CPU-only rerank / MMR / dedup evaluation harness (B6 candidate #1).

Answers, with real numbers on THIS machine (16 GB CPU, ONNX):
  - latency: cross-encoder p50/p95 per query at RERANK_CANDIDATES docs
  - quality: Spearman vs a reference ranking + Hit@k retention
  - dedup:   near-dup collapse rate at 0.90 / 0.93 / 0.95
  - MMR:     diversity (intra-list distance) vs relevance retention, λ sweep

Usage:
  python3 scripts/rerank_eval.py                      # baseline (bge-reranker-v2-m3)
  python3 scripts/rerank_eval.py --model jina-reranker-v3 --onnx-file model.onnx
  python3 scripts/rerank_eval.py --only latency
  python3 scripts/rerank_eval.py --queries 10 --candidates 30
"""

from __future__ import annotations

import argparse
import json
import statistics
import time

QUERIES = [
    # (query, category, reference_top_doc_hint)
    ("openai agent orchestration 2026", "news", "agent"),
    ("rust async runtime performance", "academic", "tokio"),
    ("bge-m3 multilingual embedding benchmark", "academic", "bge"),
    ("faceless youtube automation tools", "social", "youtube"),
    ("reddit web scraping best practices", "social", "reddit"),
    ("大模型检索增强生成", "academic", "RAG"),
    ("美团搜索排序架构", "academic", "搜索"),
    ("bilibili 创作者经济 数据分析", "social", "bilibili"),
    ("self-hosted searxng setup", "news", "searxng"),
    ("redis cache stampede prevention", "academic", "cache"),
    ("fastmcp streamable http migration", "news", "mcp"),
    ("sqlite wal backup production", "academic", "wal"),
    ("vector database hybrid search", "academic", "hybrid"),
    ("llm prompt injection defense", "academic", "injection"),
    ("dark mode ui contrast accessibility", "news", "a11y"),
    ("phoenix project management tool", "news", "phoenix"),
    ("airbnb rental arbitrage analysis", "news", "airbnb"),
    ("王者荣耀 版本更新 分析", "social", "王者"),
    ("github actions coverage gate", "news", "coverage"),
    ("mcp server authentication bearer token", "academic", "auth"),
]

# Synthetic candidates: for latency we only need doc count; for quality we
# build deterministic pseudo-documents from the query so rankings are stable.
def _candidates(query: str, n: int) -> list[str]:
    out = []
    for i in range(n):
        filler = " ".join(f"doc{i}-{j}" for j in range(8))
        # half the docs echo query terms (relevant-ish), half are noise
        if i % 2 == 0:
            out.append(f"{query} {filler}")
        else:
            out.append(f"unrelated content about {i} {filler}")
    return out


def _timeit(fn, *args):
    t0 = time.monotonic()
    result = fn(*args)
    return result, time.monotonic() - t0


def run_latency(model, queries, candidates_n, backend) -> dict:
    latencies = []
    for q, _, _ in queries:
        docs = _candidates(q, candidates_n)
        pairs = [(q, d[:512]) for d in docs]
        _, dt = _timeit(model.predict, pairs)
        latencies.append(dt)
    latencies.sort()
    return {
        "backend": backend,
        "queries": len(latencies),
        "candidates_per_query": candidates_n,
        "p50_s": round(latencies[len(latencies) // 2], 3),
        "p95_s": round(latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))], 3),
        "total_s": round(sum(latencies), 2),
    }


def run_quality(model, queries, candidates_n) -> dict:
    """Spearman of the model's ranking vs a deterministic reference score
    (term-overlap ratio — a stand-in; real judgments live in the query file)."""
    from scipy import stats as sps  # noqa: F401 — imported lazily

    spearmans = []
    hits = []
    for q, _, _ in queries:
        docs = _candidates(q, candidates_n)
        pairs = [(q, d[:512]) for d in docs]
        scores = model.predict(pairs)
        ref = [sum(1 for w in q.lower().split() if w in d.lower()) for d in docs]
        order_model = [i for i, _ in sorted(enumerate(scores), key=lambda x: -x[1])]
        order_ref = [i for i, _ in sorted(enumerate(ref), key=lambda x: -x[1])]
        rank_model = {d: i for i, d in enumerate(order_model)}
        rank_ref = {d: i for i, d in enumerate(order_ref)}
        rho = _spearman([rank_model[i] for i in range(len(docs))],
                        [rank_ref[i] for i in range(len(docs))])
        spearmans.append(rho)
        top10 = set(order_model[:10])
        ref10 = set(order_ref[:10])
        hits.append(len(top10 & ref10) / 10.0)
    return {
        "spearman_mean": round(statistics.mean(spearmans), 3),
        "hit10_retention": round(statistics.mean(hits), 3),
    }


def _spearman(a: list[float], b: list[float]) -> float:
    n = len(a)
    if n < 3:
        return 0.0
    ra = {v: i for i, v in enumerate(sorted(a))}
    rb = {v: i for i, v in enumerate(sorted(b))}
    da = [ra[v] for v in a]
    db = [rb[v] for v in b]
    ma, mb = statistics.mean(da), statistics.mean(db)
    num = sum((x - ma) * (y - mb) for x, y in zip(da, db, strict=True))
    den = (sum((x - ma) ** 2 for x in da) ** 0.5
           * sum((y - mb) ** 2 for y in db) ** 0.5)
    return num / den if den else 0.0


def run_mmr_sweep(queries, candidates_n) -> dict:
    """λ sweep: diversity (mean intra-list distance on term sets) vs relevance
    retention (mean term-overlap of selected docs)."""
    import numpy as np

    from kortex_search.diversity import mmr_select
    from kortex_search.models import Result

    out = {}
    for lam in (0.6, 0.7, 0.75, 0.8, 0.9):
        ilds, rels = [], []
        for q, _, _ in queries[:8]:
            docs = _candidates(q, candidates_n)
            res = [Result(title=f"d{i}", url=f"https://d{i}.com/", snippet=d,
                          score=max(0.01, 1.0 - i / candidates_n))
                   for i, d in enumerate(docs)]
            emb = np.eye(candidates_n)
            sel = mmr_select(res, emb, limit=5, lam=lam)
            terms = [set(d.split()) for d in docs]
            picked = [terms[int(t.url.split("/")[-2])] if t.url.split("/")[-2].isdigit()
                      else set() for t in sel]
            ild = 0.0
            for i in range(len(picked)):
                for j in range(i + 1, len(picked)):
                    a, b = picked[i], picked[j]
                    ild += len(a & b) / max(1, len(a | b))
            ilds.append(1.0 - ild / max(1, len(picked) * (len(picked) - 1) / 2))
            rels.append(statistics.mean(t.score for t in sel))
        out[str(lam)] = {
            "diversity_ild": round(statistics.mean(ilds), 3),
            "relevance_mean": round(statistics.mean(rels), 3),
        }
    return out


def run_dedup_sweep(queries, candidates_n) -> dict:
    """Near-dup collapse at 0.90/0.93/0.95 on a synthetic corpus."""
    from kortex_search.dedup import _norm_title, _similar
    corpus = [f"{q} analysis report" for q, _, _ in queries[:10]]
    corpus += [c[:-1] + "x" for c in corpus]  # near-dups (1-char diff)
    out = {}
    for thr in (0.90, 0.93, 0.95):
        seen, dups = [], 0
        for c in corpus:
            nt = _norm_title(c)
            if any(_similar(seen_nt, nt, thr) for seen_nt in seen):
                dups += 1
            else:
                seen.append(nt)
        out[str(thr)] = {"corpus": len(corpus), "collapsed": dups,
                         "collapse_rate": round(dups / len(corpus), 3)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=None,
                    help="model id (default: config RERANK_MODEL onnx_int8)")
    ap.add_argument("--onnx-file", default=None, help="onnx file name (model_int8.onnx)")
    ap.add_argument("--queries", type=int, default=len(QUERIES))
    ap.add_argument("--candidates", type=int, default=30)
    ap.add_argument("--only", choices=["latency", "quality", "mmr", "dedup"],
                    default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    queries = QUERIES[: args.queries]
    results: dict = {"queries": len(queries), "candidates": args.candidates}

    import kortex_search.rerank as rr
    if args.only in (None, "latency", "quality"):
        if args.model:
            from sentence_transformers import CrossEncoder
            model = CrossEncoder(args.model,
                                 model_kwargs={"file_name": args.onnx_file}
                                 if args.onnx_file else None)
            backend = f"{args.model}/{args.onnx_file or 'default'}"
        else:
            model = rr._get_model()
            backend = f"{rr._effective_model}/{rr.INFERENCE_BACKEND}"
        if model is None:
            print("rerank model unavailable — cannot run latency/quality")
            return 1
        if args.only in (None, "latency"):
            results["latency"] = run_latency(model, queries, args.candidates, backend)
        if args.only in (None, "quality"):
            results["quality"] = run_quality(model, queries, args.candidates)

    if args.only in (None, "mmr"):
        results["mmr_lambda_sweep"] = run_mmr_sweep(queries, args.candidates)
    if args.only in (None, "dedup"):
        results["dedup_threshold_sweep"] = run_dedup_sweep(queries, args.candidates)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
