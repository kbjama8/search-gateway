#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search-gateway benchmark harness.

Measures the performance levers that matter, with one consistent methodology:

  micro   — `dedup()` and `mmr_select()` latency vs. n (offline, synthetic data)
  model   — cold model load (fresh subprocess), warm rerank/encode latency, RSS
  search  — end-to-end `search` cold vs. warm, per-source latency, throughput
  all     — every subcommand, then a summary table

Usage:
  python scripts/bench.py micro   [--iterations N] [--json]
  python scripts/bench.py model   [--iterations N] [--json]
  python scripts/bench.py search  [--iterations N] [--queries Q] [--concurrency M] [--json]
  python scripts/bench.py all     [--json]

Methodology:
  * `time.perf_counter`; `--iterations` samples per measurement with one warmup
    run excluded (models and caches warm up once, so the median reflects steady
    state, not first-touch).
  * Reported stats: mean / median / p50 / p90 / min / max.
  * RSS via `/proc/self/status` VmRSS (KiB); peak via `resource.ru_maxrss`.
  * Cold start is measured in a **fresh subprocess** — the reranker and
    bi-encoders are process-lifetime singletons, so in-process timing cannot
    observe a cold load.
  * Every measurement either runs or reports SKIP (reason); an absent
    dependency never crashes the harness.

Notes on what each measurement actually exercises:
  * `micro` is fully offline — synthetic `Result` objects, no network, no models.
  * `model` needs the Hugging Face cache warm (no re-download, but first load
    reads from disk and builds the compute graph).
  * `search` needs Redis + the source backends; the cold `search` run uses the
    default flags, so it pays the model load that a real first query pays.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import resource
import subprocess
import sys
import time
from pathlib import Path

# Make `search_gateway` importable even if run straight from a clone without
# an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# --------------------------------------------------------------------------- #
# Measurement primitives
# --------------------------------------------------------------------------- #

def _rss_kib() -> int:
    try:
        with open("/proc/self/status", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return 0


def _peak_rss_kib() -> int:
    # ru_maxrss is KiB on Linux, bytes on macOS — normalize to KiB.
    kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return kb if sys.platform == "linux" else kb // 1024


def _stats(samples: list[float]) -> dict:
    if not samples:
        return {}
    s = sorted(samples)
    n = len(s)

    def pct(p: float) -> float:
        k = (n - 1) * p
        lo = int(k)
        hi = min(lo + 1, n - 1)
        return s[lo] + (s[hi] - s[lo]) * (k - lo)

    return {
        "n": n,
        "mean_s": round(sum(s) / n, 6),
        "median_s": round(s[n // 2], 6),
        "p50_s": round(pct(0.50), 6),
        "p90_s": round(pct(0.90), 6),
        "min_s": round(s[0], 6),
        "max_s": round(s[-1], 6),
    }


def _measure(fn, iterations: int, warmup: int = 1) -> list[float]:
    for _ in range(warmup):
        fn()
    samples: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    return samples


def _subprocess_script(script: str) -> str:
    """Run a snippet in a fresh interpreter and return its stdout."""
    r = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=600,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    if r.returncode != 0:
        return r.stderr.strip() or f"exit {r.returncode}"
    return r.stdout.strip()


# --------------------------------------------------------------------------- #
# Synthetic data (offline micro-benchmarks)
# --------------------------------------------------------------------------- #

def _synthetic_results(n: int, seed: int = 0):
    from search_gateway.models import Result

    # Cluster results so ~1/4 share a domain (exact-dup-ish) and titles are
    # near-identical variants — a realistic shape for dedup to chew on.
    n_domains = max(1, n // 4)
    results = []
    for i in range(n):
        d = i % n_domains
        title = f"Result title {i // n_domains} about information retrieval and ranking"
        url = f"https://site{d}.example.com/article/{i // n_domains}"
        snippet = _REAL_SNIPPET
        results.append(Result(title=title, url=url, snippet=snippet,
                              source="searxng", engine="bing",
                              meta={"source_type": "web"}))
    return results


def _random_embeddings(n: int, dim: int = 384, seed: int = 1):
    import numpy as np

    rng = np.random.RandomState(seed)
    v = rng.randn(n, dim).astype(np.float32)
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    return v / norms


# --------------------------------------------------------------------------- #
# micro — algorithmic hotspots, offline
# --------------------------------------------------------------------------- #

def cmd_micro(args) -> dict:
    from search_gateway.dedup import dedup
    from search_gateway.diversity import mmr_select

    results: dict = {}
    for n in args.sizes:
        docs = _synthetic_results(n)
        emb = _random_embeddings(n)

        # dedup: title/URL-only path (no embeddings)
        try:
            s = _measure(lambda: dedup(docs), args.iterations)
            results[f"dedup_title_only_n{n}"] = _stats(s)
        except Exception as exc:  # noqa: BLE001
            results[f"dedup_title_only_n{n}"] = {"skip": str(exc)}

        # dedup: embedding path
        try:
            s = _measure(lambda: dedup(docs, embeddings=emb), args.iterations)
            results[f"dedup_embedding_n{n}"] = _stats(s)
        except Exception as exc:  # noqa: BLE001
            results[f"dedup_embedding_n{n}"] = {"skip": str(exc)}

        # mmr: greedy diversity over the same docs
        limit = min(10, n)
        for r in docs:
            r.score = random.Random(r.title).uniform(0.5, 10.0)
        try:
            s = _measure(lambda: mmr_select(docs, emb, limit), args.iterations)
            results[f"mmr_n{n}_limit{limit}"] = _stats(s)
        except Exception as exc:  # noqa: BLE001
            results[f"mmr_n{n}_limit{limit}"] = {"skip": str(exc)}

    return {"micro": results}


# --------------------------------------------------------------------------- #
# model — cold load (subprocess) + warm inference + RSS
# --------------------------------------------------------------------------- #

_COLD_MODEL_SCRIPT = r"""
import time, json
def rss():
    try:
        for line in open("/proc/self/status"):
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except Exception:
        pass
    return 0
from search_gateway import embeddings, rerank
out = {}
out["rss_before_kib"] = rss()
t0 = time.perf_counter()
embeddings._get_model()
out["embed_load_s"] = round(time.perf_counter() - t0, 3)
out["embed_loaded"] = embeddings._get_model() is not None
out["rss_after_embed_kib"] = rss()
t0 = time.perf_counter()
rerank._get_model()
out["rerank_load_s"] = round(time.perf_counter() - t0, 3)
out["rerank_loaded"] = rerank._get_model() is not None
out["rss_after_rerank_kib"] = rss()
print(json.dumps(out))
"""


def cmd_model(args) -> dict:
    from search_gateway import embeddings, rerank
    from search_gateway.models import Result

    out: dict = {"model": {}}

    # Cold load (fresh process).
    raw = _subprocess_script(_COLD_MODEL_SCRIPT)
    try:
        out["model"]["cold"] = json.loads(raw)
    except json.JSONDecodeError:
        out["model"]["cold"] = {"error": raw[:300]}

    # Warm inference (in-process). If a model isn't cached, report skip.
    rss_before = _rss_kib()
    embed_model = embeddings._get_model()
    rerank_model = rerank._get_model()

    if embed_model is None:
        out["model"]["warm_embed"] = {"skip": "embed model unavailable"}
    else:
        docs = [f"document number {i} about ranking and retrieval" for i in range(50)]
        s = _measure(lambda: embeddings.encode(docs), args.iterations)
        out["model"]["warm_embed_encode_50docs"] = _stats(s)

    if rerank_model is None:
        out["model"]["warm_rerank"] = {"skip": "rerank model unavailable"}
    else:
        rs = [Result(title=f"t{i}", url=f"u{i}", snippet=_REAL_SNIPPET)
              for i in range(30)]
        s = _measure(lambda: rerank.rerank("test query", rs), args.iterations)
        out["model"]["warm_rerank_top30"] = _stats(s)

    out["model"]["rss_warm_kib"] = _rss_kib()
    out["model"]["rss_delta_kib"] = _rss_kib() - rss_before
    out["model"]["peak_rss_kib"] = _peak_rss_kib()
    return out


# --------------------------------------------------------------------------- #
# search — end-to-end cold/warm, per-source latency, throughput
# --------------------------------------------------------------------------- #

def _cold_search_script(query: str) -> str:
    return f'''
import asyncio, time, json
from search_gateway import orchestrator
async def main():
    t0 = time.perf_counter()
    res = await orchestrator.search({query!r}, None, category="general", limit=10)
    dt = time.perf_counter() - t0
    print(json.dumps({{"elapsed_s": round(dt, 3), "count": res.get("count"),
                       "partial": res.get("partial"), "cached": res.get("cached")}}))
asyncio.run(main())
'''

_DEFAULT_QUERIES = [
    "information retrieval ranking",
    "transformer attention mechanism",
    "rust async runtime comparison",
]


def _unique_query(base: str) -> str:
    """Append a nonce so the query misses the Redis final-result cache — the
    pipeline (fan-out → fuse → rerank → MMR) is what we want to time, not a
    cache hit."""
    return f"{base} {time.time_ns()}"


# Realistic ~270-char snippet: word-level tokens, not pathological repeats, so
# the cross-encoder timings reflect production inputs rather than 300
# single-character tokens.
_REAL_SNIPPET = (
    "This paper proposes a novel approach to information retrieval using "
    "reciprocal rank fusion across heterogeneous sources with varying score "
    "distributions and explores the trade-offs between fusion and re-ranking "
    "strategies on a corpus of academic documents and web results."
)


def cmd_search(args) -> dict:
    from search_gateway import orchestrator
    from search_gateway.sources import ALL_SOURCES
    from search_gateway.config import DEFAULT_SOURCES

    out: dict = {"search": {}}

    # Cold first query (fresh process, default flags → pays model load).
    raw = _subprocess_script(_cold_search_script(_unique_query("cold benchmark")))
    try:
        out["search"]["cold_first_query"] = json.loads(raw)
    except json.JSONDecodeError:
        out["search"]["cold_first_query"] = {"error": raw[:300]}

    # Warm queries (unique query per run → real pipeline, not a cache hit).
    for q in args.queries:
        try:
            def run():
                asyncio.run(orchestrator.search(
                    _unique_query(q), list(DEFAULT_SOURCES), category="general",
                    limit=5, expand=False))
            s = _measure(run, args.iterations)
            out["search"][f"warm_{q[:20]}"] = _stats(s)
        except Exception as exc:  # noqa: BLE001
            out["search"][f"warm_{q[:20]}"] = {"skip": str(exc)}

    # Per-source latency (each source in isolation).
    for name in DEFAULT_SOURCES:
        src = ALL_SOURCES.get(name)
        if src is None:
            continue
        try:
            def run_src():
                asyncio.run(src.search(_unique_query("benchmark"), limit=5))
            s = _measure(run_src, args.iterations)
            out["search"][f"source_{name}"] = _stats(s)
        except Exception as exc:  # noqa: BLE001
            out["search"][f"source_{name}"] = {"skip": str(exc)}

    # Concurrent throughput (unique queries per task).
    try:
        async def _throughput():
            t0 = time.perf_counter()
            await asyncio.gather(*[
                orchestrator.search(_unique_query("concurrency probe"),
                                    list(DEFAULT_SOURCES), category="general",
                                    limit=5, expand=False)
                for _ in range(args.concurrency)
            ])
            return time.perf_counter() - t0

        s = _measure(lambda: asyncio.run(_throughput()), max(1, args.iterations // 2), warmup=1)
        out["search"]["concurrency"] = {
            "m": args.concurrency,
            **_stats(s),
            "qps": round(args.concurrency / (_stats(s)["mean_s"] or 1), 2),
        }
    except Exception as exc:  # noqa: BLE001
        out["search"]["concurrency"] = {"skip": str(exc)}

    return out


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

def _fmt_row(key: str, s: dict) -> str:
    if "skip" in s or "error" in s:
        return f"  {key:<34} SKIP — {s.get('skip') or s.get('error')}"
    if "mean_s" not in s:
        return f"  {key:<34} {s}"
    return (f"  {key:<34} mean {s['mean_s']*1000:>8.2f} ms   "
            f"p50 {s['p50_s']*1000:>8.2f} ms   p90 {s['p90_s']*1000:>8.2f} ms   "
            f"(min {s['min_s']*1000:.2f} / max {s['max_s']*1000:.2f}, n={s['n']})")


def _report(data: dict) -> None:
    print("\n" + "=" * 96)
    for section, measurements in data.items():
        print(f"[{section}]")
        if isinstance(measurements, dict):
            for key, value in measurements.items():
                if key == "cold":
                    print("  cold (fresh subprocess):")
                    if isinstance(value, dict):
                        for k, v in value.items():
                            print(f"    {k:<24} {v}")
                    continue
                if isinstance(value, dict) and ("mean_s" in value or "skip" in value):
                    print(_fmt_row(key, value))
                else:
                    print(f"  {key:<34} {value}")
    print("=" * 96)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="search-gateway benchmark harness")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("micro")
    p.add_argument("--iterations", type=int, default=5)
    p.add_argument("--sizes", type=int, nargs="+", default=[10, 30, 100, 180])
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_micro)

    p = sub.add_parser("model")
    p.add_argument("--iterations", type=int, default=5)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_model)

    p = sub.add_parser("search")
    p.add_argument("--iterations", type=int, default=3)
    p.add_argument("--queries", type=str, nargs="+", default=_DEFAULT_QUERIES)
    p.add_argument("--concurrency", type=int, default=5)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("all")
    p.add_argument("--iterations", type=int, default=3)
    p.add_argument("--sizes", type=int, nargs="+", default=[10, 30, 100, 180])
    p.add_argument("--queries", type=str, nargs="+", default=_DEFAULT_QUERIES)
    p.add_argument("--concurrency", type=int, default=5)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=None)

    args = parser.parse_args(argv)

    if args.command == "all":
        data = {}
        data.update(cmd_micro(args))
        data.update(cmd_model(args))
        data.update(cmd_search(args))
    elif args.command in ("micro", "model", "search"):
        data = args.fn(args)
    else:
        parser.print_help()
        return 2

    if getattr(args, "json", False):
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        _report(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
