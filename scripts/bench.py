#!/usr/bin/env python3
"""search-gateway benchmark harness.

Measures the performance levers that matter, with one consistent methodology:

  micro   — `dedup()` and `mmr_select()` latency vs. n (offline, synthetic data)
  model   — cold model load (fresh subprocess), warm rerank/encode latency, RSS
  search  — end-to-end `search` cold vs. warm, per-source latency, throughput
  browser — SLOW command: egress-floor overhead, L2 proxy roundtrip, and
            (when the stealth tier is usable) Camoufox launch/navigate/
            teardown, profile rotation, RSS delta — every measurement SKIPs
            with a reason when its dependency is absent
  all     — every subcommand, then a summary table

Usage:
  python scripts/bench.py micro   [--iterations N] [--json]
  python scripts/bench.py model   [--iterations N] [--json]
  python scripts/bench.py search  [--iterations N] [--queries Q] [--concurrency M] [--json]
  python scripts/bench.py browser [--iterations N] [--url URL] [--json]
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
  * `browser` needs nothing beyond stdlib for the floor/proxy measurements;
    the Camoufox launch measurements need the stealth tier enabled AND the
    L3 filter installed/covered (D7.1) — otherwise they SKIP with the reason
    the gateway itself would surface.
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
    # Operator-run dev harness: the only snippets ever executed are the module
    # constants below (plus a query string the operator types themselves).
    r = subprocess.run(  # noqa: S603 — operator-authored snippets only
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
            s = _measure(lambda docs=docs: dedup(docs), args.iterations)
            results[f"dedup_title_only_n{n}"] = _stats(s)
        except Exception as exc:  # noqa: BLE001
            results[f"dedup_title_only_n{n}"] = {"skip": str(exc)}

        # dedup: embedding path
        try:
            s = _measure(lambda docs=docs, emb=emb: dedup(docs, embeddings=emb),
                         args.iterations)
            results[f"dedup_embedding_n{n}"] = _stats(s)
        except Exception as exc:  # noqa: BLE001
            results[f"dedup_embedding_n{n}"] = {"skip": str(exc)}

        # mmr: greedy diversity over the same docs
        limit = min(10, n)
        for r in docs:
            # Seeded per-title pseudo-random scores: deterministic synthetic
            # input for stable benchmark numbers, not a security boundary.
            r.score = random.Random(r.title).uniform(0.5, 10.0)  # noqa: S311
        try:
            s = _measure(lambda docs=docs, emb=emb, limit=limit:
                         mmr_select(docs, emb, limit), args.iterations)
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
    from search_gateway.config import DEFAULT_SOURCES
    from search_gateway.sources import ALL_SOURCES

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
            def run(q=q):
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
            def run_src(src=src):
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
# browser — containment tier: floor overhead, L2 proxy, Camoufox (slow)
# --------------------------------------------------------------------------- #

_FLOOR_CORPUS = [
    "https://example.com/article/1",
    "https://www.google.com/search?q=rust",
    "https://api.deepseek.com/chat/completions",
    "https://r.jina.ai/https://example.com/",
    "http://169.254.169.254/latest/meta-data",
    "http://10.1.2.3/private",
    "http://192.168.1.1/router",
    "http://metadata.google.internal/computeMetadata/v1/",
    "https://arxiv.org/abs/2401.00001",
    "https://news.ycombinator.com/item?id=1",
] * 10  # 100 samples per iteration


def _floor_cost() -> dict:
    from search_gateway.extract import egress

    baseline = _measure(
        lambda: [egress._host_of_url(u) for u in _FLOOR_CORPUS], 1)
    checked = _measure(
        lambda: [egress.is_always_blocked_url(u) for u in _FLOOR_CORPUS],
        max(1, 1))
    return {
        "baseline_urlsplit_100": _stats(baseline),
        "floor_checked_100": _stats(checked),
    }


def _proxy_roundtrip() -> dict:
    """EgressProxy CONNECT roundtrip (loopback echo) vs direct connect —
    the per-op cost of the L2 forced-proxy path."""
    import asyncio

    from search_gateway.extract import egress

    async def _measure_roundtrips(iterations: int) -> tuple[list[float], list[float]]:
        srv = await asyncio.start_server(
            lambda r, w: asyncio.ensure_future(_echo(r, w)), "127.0.0.1", 0)
        target_port = srv.sockets[0].getsockname()[1]
        proxy = egress.EgressProxy()
        await proxy.start()
        direct: list[float] = []
        proxied: list[float] = []
        for _i in range(iterations):
            t0 = time.perf_counter()
            r, w = await asyncio.open_connection("127.0.0.1", target_port)
            w.write(b"ping\n")
            await w.drain()
            await r.read(64)
            w.close()
            direct.append(time.perf_counter() - t0)

            t0 = time.perf_counter()
            r, w = await asyncio.open_connection("127.0.0.1", proxy.port)
            w.write(f"CONNECT 127.0.0.1:{target_port} HTTP/1.1\r\n\r\n".encode())
            await w.drain()
            await r.readline()
            await r.readline()
            w.write(b"ping\n")
            await w.drain()
            await r.read(64)
            w.close()
            proxied.append(time.perf_counter() - t0)
        await proxy.stop()
        srv.close()
        await srv.wait_closed()
        return direct, proxied

    async def _echo(reader, writer):
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()

    def _run(iterations: int) -> tuple[list[float], list[float]]:
        return asyncio.run(_measure_roundtrips(iterations))

    try:
        direct, proxied = _run(1)  # warmup
        direct, proxied = _run(3)
    except Exception as exc:  # noqa: BLE001
        return {"skip": str(exc)}
    return {
        "direct_loopback": _stats(direct),
        "via_egress_proxy": _stats(proxied),
        "overhead_ms": round((sum(proxied) / len(proxied)
                              - sum(direct) / len(direct)) * 1000, 3),
    }


def _camoufox_measurements(url: str) -> dict:
    """Launch/navigate/teardown + profile rotation + RSS (SKIPs when the
    stealth tier or the L3 filter is not usable — the same reasons the
    gateway would refuse)."""
    import asyncio

    from search_gateway.extract import camoufox, harden

    out: dict = {}

    def _skip_if_unusable() -> str | None:
        ok, reason = camoufox.available()
        if not ok:
            return reason
        st = harden.status()
        if not st["installed"]:
            return "L3 filter not installed (D7.1) — run 'search-gateway harden --install --sudo'"
        if not st["covered"]:
            return ("gateway not inside the scoped cgroup — run under "
                    "'systemd-run --user --scope --unit=sg-egress'")
        return None

    reason = _skip_if_unusable()
    if reason:
        out["launch"] = {"skip": reason}
        out["navigate_extract"] = {"skip": reason}
        out["profile_rotation"] = {"skip": reason}
        return out

    async def _ops(iterations: int):
        cold = None
        warm = []
        nav: list[float] = []
        rss_delta = 0
        for i in range(iterations + 1):  # first = cold
            t0 = time.perf_counter()
            browser, why = await camoufox.launch(f"bench-{i % 3}")
            dt = time.perf_counter() - t0
            if browser is None:
                return {"skip": f"launch failed: {why}"}
            if i == 0:
                cold = dt
                rss_delta = _rss_kib()
            else:
                warm.append(dt)
            t0 = time.perf_counter()
            try:
                await camoufox.html(browser, url, timeout_ms=30000)
            finally:
                await browser.close()
            nav.append(time.perf_counter() - t0)
        return {"cold": cold, "warm": warm, "nav": nav, "rss_delta": rss_delta}

    try:
        data = asyncio.run(_ops(1))  # warmup
        data = asyncio.run(_ops(2))
    except Exception as exc:  # noqa: BLE001
        out["launch"] = {"skip": str(exc)}
        return out
    if "skip" in data:
        out["launch"] = {"skip": data["skip"]}
        return out
    out["launch_cold_s"] = round(data["cold"], 3)
    out["launch_warm"] = _stats(data["warm"])
    out["navigate_extract"] = _stats(data["nav"])
    out["rss_after_launch_kib"] = data["rss_delta"]
    return out


def cmd_browser(args) -> dict:
    out: dict = {"browser": {}}
    out["browser"]["floor_check"] = _floor_cost()
    out["browser"]["proxy_roundtrip"] = _proxy_roundtrip()
    out["browser"].update(_camoufox_measurements(args.url))
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

    p = sub.add_parser("browser",
                       help="SLOW: containment tier (floor overhead, L2 proxy "
                            "roundtrip, Camoufox launch/navigate when usable)")
    p.add_argument("--iterations", type=int, default=3)
    p.add_argument("--url", type=str,
                   default="https://example.com/",
                   help="target URL for the navigate→extract measurement")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_browser)

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
    elif args.command in ("micro", "model", "search", "browser"):
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
