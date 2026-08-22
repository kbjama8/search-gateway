"""Search orchestrator — fan-out → fusion → dedup → re-rank → diversity → cache.

Pipeline: per-source cache → (optional) LLM query expansion → concurrent fan-out
(asyncio.wait, keeps completed sources even on timeout) → weighted RRF fusion →
dedup (URL + title + embedding) → cross-encoder re-rank → MMR diversity →
freshness filter → cache.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import re
import time
from typing import Any

from . import cache, llm, ratelimit, stats
from .config import (
    ADAPTIVE_TIMEOUT,
    ADAPTIVE_TIMEOUT_FACTOR,
    ADAPTIVE_TIMEOUT_MAX,
    ADAPTIVE_TIMEOUT_MIN,
    DEFAULT_LIMIT,
    DEFAULT_SOURCES,
    EMBEDDING_DEDUP,
    EXPANSION_GATE_RESULTS,
    FRESHNESS_FILTER,
    GLOBAL_TIMEOUT,
    MMR_ENABLED,
    MMR_LAMBDA,
    MMR_LAMBDA_BY_CATEGORY,
    PER_SOURCE_TIMEOUT,
    QUERY_EXPANSION,
    RATE_LIMIT_INTERVAL,
    RATE_LIMITED_SOURCES,
    RERANK_CANDIDATES,
    SEMANTIC_RERANK,
)
from .dedup import dedup
from .diversity import mmr_select
from .embeddings import cjk_dominant, encode
from .fusion import rrf_fuse
from .models import Result
from .rerank import rerank
from .sources import get_sources
from .sources.base import SourceError

logger = logging.getLogger("search_gateway.orchestrator")

# Singleflight: concurrent searches for the same (source, query) share one
# in-flight task instead of hammering the backend N times.
_inflight: dict[tuple[str, str], asyncio.Task] = {}


async def _singleflight(source, query: str, limit: int, category: str,
                        freshness: str | None, year_from: int | None,
                        open_access_only: bool) -> tuple[str, Any]:
    """Run `_run_one` under a per-(source, query) in-flight dedup."""
    key = (source.name, query.lower().strip())
    task = _inflight.get(key)
    if task is not None and not task.done():
        with contextlib.suppress(Exception):  # fall through to a fresh run
            return await asyncio.shield(task)
    task = asyncio.ensure_future(
        _run_one(source, query, limit, category, freshness, year_from,
                 open_access_only))
    _inflight[key] = task
    try:
        return await task
    finally:
        _inflight.pop(key, None)

_FRESHNESS_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}

_DATE_PATTERNS = [
    (re.compile(r"(\d{4})-(\d{2})-(\d{2})"), "%Y-%m-%d"),
    (re.compile(r"\w{3} \w{3} \d{1,2} \d{2}:\d{2}:\d{2} [+-]\d{4} (\d{4})"), "%Y"),
    (re.compile(r"(\d{4})(\d{2})(\d{2})"), "%Y%m%d"),
]


def _parse_date(s: str) -> dt.datetime | None:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):  # ISO first
        try:
            return dt.datetime.strptime(s[: len(fmt)], fmt)  # noqa: DTZ007 — naive by design; callers normalize tz
        except ValueError:
            continue
    for pat, _ in _DATE_PATTERNS:
        m = pat.search(s)
        if m:
            groups = m.groups()
            try:
                if len(groups) == 1:
                    return dt.datetime(int(groups[0]), 1, 1)  # noqa: DTZ001 — naive; callers normalize tz
                return dt.datetime(*[int(g) for g in groups])  # noqa: DTZ001 — naive; callers normalize tz
            except (ValueError, TypeError):
                return None
    return None


def _filter_fresh(results: list[Result], freshness: str | None) -> list[Result]:
    if not freshness or freshness not in _FRESHNESS_DAYS or not FRESHNESS_FILTER:
        return results
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=_FRESHNESS_DAYS[freshness])
    out = []
    for r in results:
        d = _parse_date(r.published or "")
        if d is None:
            out.append(r)  # unparseable → keep exactly once (don't drop)
            continue
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.UTC)
        if d >= cutoff:
            out.append(r)
    return out


def _filter_year(results: list[Result], year_from: int | None) -> list[Result]:
    if not year_from:
        return results
    return [r for r in results
            if (r.meta.get("year") is None or r.meta.get("year") >= year_from)]


def _filter_oa(results: list[Result]) -> list[Result]:
    # keep known-OA or unknown; drop only known-closed-access
    return [r for r in results if r.meta.get("is_oa") is not False]


def _filter_key(freshness: str | None, year_from: int | None,
                open_access_only: bool) -> str:
    parts = []
    if freshness:
        parts.append(f"fr:{freshness}")
    if year_from:
        parts.append(f"yr:{year_from}")
    if open_access_only:
        parts.append("oa")
    return "|".join(parts)


async def _expand_query(query: str) -> list[str]:
    """LLM query expansion → up to 2 alternative search phrasings."""
    if not QUERY_EXPANSION or not llm.available():
        return []
    try:
        prompt = (
            "Generate 2 alternative search queries that would surface different "
            "relevant information about the SAME topic as the query below. "
            "Each query must be a complete meaningful phrase of 3 or more words. "
            "Do NOT output single keywords, fragments, or the original query. "
            "Output exactly 2 lines, nothing else.\n\n"
            f"Query: {query}"
        )
        out = await llm.complete([{"role": "user", "content": prompt}],
                                 max_tokens=150, temperature=0.2, thinking=False)
        variants = []
        for ln in out.splitlines():
            v = ln.strip().lstrip("-•1234567890. ").strip()
            words = v.split()
            # require a meaningful multi-word phrase
            if len(words) >= 3 and v.lower() != query.lower():
                variants.append(v)
        return variants[:2]
    except Exception as exc:  # noqa: BLE001
        logger.warning("query expansion failed: %s", exc)
        return []


def _adaptive_timeout(name: str, fallback: float = PER_SOURCE_TIMEOUT) -> float:
    """min(p95(source) x factor, cap) with a floor; fallback when unknown."""
    if not ADAPTIVE_TIMEOUT:
        return fallback
    p95 = stats.latency_percentiles(name).get("p95_s", 0.0)
    if p95 <= 0:
        return fallback
    return max(ADAPTIVE_TIMEOUT_MIN, min(p95 * ADAPTIVE_TIMEOUT_FACTOR,
                                         ADAPTIVE_TIMEOUT_MAX))


def _expansion_needed(base_total: int, gate: int = EXPANSION_GATE_RESULTS) -> bool:
    return base_total < gate


def _category_lambda(category: str) -> float:
    return MMR_LAMBDA_BY_CATEGORY.get(category, MMR_LAMBDA)


async def _run_one(source, query: str, limit: int, category: str,
                   freshness: str | None, year_from: int | None = None,
                   open_access_only: bool = False) -> tuple[str, Any]:
    """Run a single source: rate-limit → per-source cache → search → stats.

    The search call is wrapped in an ADAPTIVE per-source timeout:
    `min(p95(source) * factor, cap)` — stragglers die early, healthy sources
    get headroom. Unknown sources use the static PER_SOURCE_TIMEOUT.
    """
    name = source.name
    fkey = _filter_key(freshness, year_from, open_access_only)
    try:
        if cache.source_recently_failed(name, query, category):
            return name, "skipped (recent failure)"

        if name in RATE_LIMITED_SOURCES:
            await ratelimit.wait_if_needed(name, RATE_LIMIT_INTERVAL)
        await ratelimit.enforce_daily_budget(name)

        cached = cache.get_source(name, query, category, limit=limit, filters=fkey)
        if cached is not None:
            return name, [Result(**d) for d in cached]

        timeout = _adaptive_timeout(name)

        t0 = time.monotonic()
        if name == "searxng":
            coro = source.search(query, limit=limit, category=category,
                                 freshness=freshness)
        elif name == "openalex":
            coro = source.search(query, limit=limit, year_from=year_from,
                                 open_access_only=open_access_only)
        elif name == "crossref":
            coro = source.search(query, limit=limit, year_from=year_from)
        else:
            coro = source.search(query, limit=limit)
        try:
            results = await asyncio.wait_for(coro, timeout=timeout)
        except TimeoutError as exc:
            raise SourceError(
                f"timeout ({timeout:.1f}s, adaptive): {name}"
            ) from exc
        elapsed = time.monotonic() - t0

        if not isinstance(results, list):
            results = []
        # enforce the standardized source_type on every result (backward-compat)
        for r in results:
            if isinstance(r, Result):
                r.meta.setdefault("source_type", source.source_type)
        if freshness:
            results = _filter_fresh(results, freshness)
        if year_from and name not in ("openalex", "crossref"):
            results = _filter_year(results, year_from)
        if open_access_only and name != "openalex":
            results = _filter_oa(results)

        cache.set_source(name, query, category, [r.to_dict() for r in results],
                         limit=limit, filters=fkey)
        stats.record(name, True, elapsed)
        return name, results
    except SourceError as exc:
        stats.record_error(name)
        cache.mark_source_failed(name, query, category)
        return name, f"error: {exc}"
    except Exception as exc:  # noqa: BLE001
        stats.record_error(name)
        cache.mark_source_failed(name, query, category)
        return name, f"error: {type(exc).__name__}: {exc}"


async def search(query: str, sources: list[str] | None, category: str = "general",
                 limit: int = DEFAULT_LIMIT, freshness: str | None = None,
                 expand: bool = QUERY_EXPANSION, year_from: int | None = None,
                 open_access_only: bool = False) -> dict[str, Any]:
    start = time.monotonic()
    source_names = [s for s in (sources or DEFAULT_SOURCES)]
    fkey = _filter_key(freshness, year_from, open_access_only)

    cached = cache.get(query, source_names, category, limit, filters=fkey)
    if cached is not None:
        return {"query": query, "results": cached, "count": len(cached),
                "sources": {}, "cached": True,
                "elapsed_ms": int((time.monotonic() - start) * 1000)}

    objs = get_sources(source_names)
    statuses: dict[str, Any] = {}
    ranked_lists: list[list[Result]] = []

    # Phase 1: base fan-out (original query on all requested sources).
    tasks = {asyncio.ensure_future(
        _singleflight(s, query, limit, category, freshness, year_from,
                      open_access_only)
    ): (s.name, s.name)
             for s in objs}
    done, pending = await asyncio.wait(tasks, timeout=GLOBAL_TIMEOUT)

    for fut in done:
        label, name = tasks[fut]
        try:
            _, outcome = fut.result()
        except Exception as exc:  # noqa: BLE001
            outcome = f"error: {type(exc).__name__}: {exc}"
        if isinstance(outcome, list):
            if outcome:
                ranked_lists.append(outcome)
            if label:
                statuses[name] = f"ok ({len(outcome)})"
        else:
            if label:
                statuses[name] = outcome

    pending_names = []
    for fut in pending:
        label, name = tasks[fut]
        if label:
            pending_names.append(name)
            statuses[name] = "pending (timeout)"
        fut.cancel()

    # Phase 2: expansion fan-out ONLY when the base results are weak
    # (gated rewrite — variants are worth the latency when the base is thin).
    base_total = sum(len(rl) for rl in ranked_lists)
    if expand and _expansion_needed(base_total):
        variants = await _expand_query(query)
        if variants:
            tasks2 = {asyncio.ensure_future(
                _singleflight(s, v, limit, category, freshness, year_from,
                              open_access_only)
            ): ("", s.name)
                      for v in variants for s in get_sources(["searxng", "exa"])}
            done2, pending2 = await asyncio.wait(tasks2, timeout=GLOBAL_TIMEOUT)
            for fut in done2:
                _, outcome = fut.result()
                if isinstance(outcome, list) and outcome:
                    ranked_lists.append(outcome)
            for fut in pending2:
                fut.cancel()

    # fusion (weighted RRF + exact dedup) → near-dup dedup (embedding)
    t_fusion = time.monotonic()
    fused = rrf_fuse(ranked_lists)
    dedup_docs = [(r.title + " " + r.snippet[:200]) for r in fused]
    multilingual = cjk_dominant(dedup_docs)
    emb_for_dedup = None
    if EMBEDDING_DEDUP and len(fused) > 1:
        emb_for_dedup = encode(dedup_docs, multilingual=multilingual)
    fused = dedup(fused, embeddings=emb_for_dedup)
    t_dedup = time.monotonic()

    # semantic re-rank the top candidates (full re-ranked list, no truncation)
    reranked = None
    if SEMANTIC_RERANK and len(fused) > limit:
        reranked = rerank(query, fused[:RERANK_CANDIDATES])
    else:
        reranked = fused
    t_rerank = time.monotonic()

    # MMR diversity on the re-ranked candidates (per-category λ)
    if MMR_ENABLED and len(reranked) > limit:
        emb_for_mmr = encode([(r.title + " " + r.snippet[:200]) for r in reranked],
                             multilingual=multilingual)
        final = mmr_select(reranked, emb_for_mmr, limit,
                          lam=_category_lambda(category))
    else:
        final = reranked[:limit]
    t_mmr = time.monotonic()

    result_dicts = [r.to_dict() for r in final]
    cache.set(query, source_names, category, limit, result_dicts, filters=fkey)

    return {
        "query": query,
        "results": result_dicts,
        "count": len(result_dicts),
        "sources": statuses,
        "cached": False,
        "reranked": SEMANTIC_RERANK,
        "partial": bool(pending_names),
        "pending": pending_names,
        "elapsed_ms": int((time.monotonic() - start) * 1000),
        "stage_ms": {
            "fanout": int((t_fusion - start) * 1000),
            "fusion_dedup": int((t_dedup - t_fusion) * 1000),
            "rerank": int((t_rerank - t_dedup) * 1000),
            "mmr": int((t_mmr - t_rerank) * 1000),
            "total": int((time.monotonic() - start) * 1000),
        },
    }
