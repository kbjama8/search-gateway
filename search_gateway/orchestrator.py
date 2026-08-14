# -*- coding: utf-8 -*-
"""Search orchestrator — fan-out → fusion → dedup → re-rank → diversity → cache.

Pipeline: per-source cache → (optional) LLM query expansion → concurrent fan-out
(asyncio.wait, keeps completed sources even on timeout) → weighted RRF fusion →
dedup (URL + title + embedding) → cross-encoder re-rank → MMR diversity →
freshness filter → cache.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
import time
from typing import Any, Optional

from . import cache, llm, ratelimit, stats
from .config import (DEFAULT_LIMIT, DEFAULT_SOURCES, FRESHNESS_FILTER,
                     GLOBAL_TIMEOUT, MMR_ENABLED, QUERY_EXPANSION,
                     RATE_LIMITED_SOURCES, RATE_LIMIT_INTERVAL,
                     RERANK_CANDIDATES, SEMANTIC_RERANK, EMBEDDING_DEDUP)
from .dedup import dedup
from .diversity import mmr_select
from .embeddings import cjk_dominant, encode
from .fusion import rrf_fuse
from .models import Result
from .rerank import rerank
from .sources import get_sources
from .sources.base import SourceError

logger = logging.getLogger("search_gateway.orchestrator")

_FRESHNESS_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}

_DATE_PATTERNS = [
    (re.compile(r"(\d{4})-(\d{2})-(\d{2})"), "%Y-%m-%d"),
    (re.compile(r"\w{3} \w{3} \d{1,2} \d{2}:\d{2}:\d{2} [+-]\d{4} (\d{4})"), "%Y"),
    (re.compile(r"(\d{4})(\d{2})(\d{2})"), "%Y%m%d"),
]


def _parse_date(s: str) -> Optional[dt.datetime]:
    if not s:
        return None
    s = str(s).strip()
    for _ in range(1):  # try direct ISO first
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return dt.datetime.strptime(s[: len(fmt)], fmt)
            except ValueError:
                continue
    for pat, _ in _DATE_PATTERNS:
        m = pat.search(s)
        if m:
            groups = m.groups()
            try:
                if len(groups) == 1:
                    return dt.datetime(int(groups[0]), 1, 1)
                return dt.datetime(*[int(g) for g in groups])
            except (ValueError, TypeError):
                return None
    return None


def _filter_fresh(results: list[Result], freshness: Optional[str]) -> list[Result]:
    if not freshness or freshness not in _FRESHNESS_DAYS or not FRESHNESS_FILTER:
        return results
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=_FRESHNESS_DAYS[freshness])
    out = []
    for r in results:
        d = _parse_date(r.published or "")
        if d is None:
            out.append(r)  # unparseable → keep (don't drop)
        elif d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        if d is None or d >= cutoff:
            out.append(r)
    return out


def _filter_year(results: list[Result], year_from: Optional[int]) -> list[Result]:
    if not year_from:
        return results
    return [r for r in results
            if (r.meta.get("year") is None or r.meta.get("year") >= year_from)]


def _filter_oa(results: list[Result]) -> list[Result]:
    # keep known-OA or unknown; drop only known-closed-access
    return [r for r in results if r.meta.get("is_oa") is not False]


def _filter_key(freshness: Optional[str], year_from: Optional[int],
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


async def _run_one(source, query: str, limit: int, category: str,
                   freshness: Optional[str], year_from: Optional[int] = None,
                   open_access_only: bool = False) -> tuple[str, Any]:
    """Run a single source: rate-limit → per-source cache → search → stats."""
    name = source.name
    fkey = _filter_key(freshness, year_from, open_access_only)
    try:
        if name in RATE_LIMITED_SOURCES:
            await ratelimit.wait_if_needed(name, RATE_LIMIT_INTERVAL)

        cached = cache.get_source(name, query, category, filters=fkey)
        if cached is not None:
            return name, [Result(**d) for d in cached]

        t0 = time.monotonic()
        if name == "searxng":
            results = await source.search(query, limit=limit, category=category,
                                          freshness=freshness)
        elif name == "openalex":
            results = await source.search(query, limit=limit, year_from=year_from,
                                          open_access_only=open_access_only)
        elif name == "crossref":
            results = await source.search(query, limit=limit, year_from=year_from)
        else:
            results = await source.search(query, limit=limit)
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

        cache.set_source(name, query, category, [r.to_dict() for r in results], filters=fkey)
        stats.record(name, True, elapsed)
        return name, results
    except SourceError as exc:
        stats.record_error(name)
        return name, f"error: {exc}"
    except Exception as exc:  # noqa: BLE001
        stats.record_error(name)
        return name, f"error: {type(exc).__name__}: {exc}"


async def search(query: str, sources: Optional[list[str]], category: str = "general",
                 limit: int = DEFAULT_LIMIT, freshness: Optional[str] = None,
                 expand: bool = QUERY_EXPANSION, year_from: Optional[int] = None,
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

    # Build all work items concurrently: the main fan-out (original query, all
    # requested sources) + expansion fan-out (variants, fast web sources only).
    work: list[tuple[Any, str, str]] = [(s, query, s.name) for s in objs]
    if expand:
        for variant in await _expand_query(query):
            for src in get_sources(["searxng", "exa"]):
                work.append((src, variant, ""))  # empty label → not in statuses

    tasks = {asyncio.ensure_future(_run_one(s, q, limit, category, freshness, year_from, open_access_only)): (label, s.name)
             for (s, q, label) in work}
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

    # fusion (weighted RRF + exact dedup) → near-dup dedup (embedding)
    fused = rrf_fuse(ranked_lists)
    dedup_docs = [(r.title + " " + r.snippet[:200]) for r in fused]
    multilingual = cjk_dominant(dedup_docs)
    emb_for_dedup = None
    if EMBEDDING_DEDUP and len(fused) > 1:
        emb_for_dedup = encode(dedup_docs, multilingual=multilingual)
    fused = dedup(fused, embeddings=emb_for_dedup)

    # semantic re-rank the top candidates (full re-ranked list, no truncation)
    reranked = None
    if SEMANTIC_RERANK and len(fused) > limit:
        reranked = rerank(query, fused[:RERANK_CANDIDATES])
    else:
        reranked = fused

    # MMR diversity on the re-ranked candidates
    if MMR_ENABLED and len(reranked) > limit:
        emb_for_mmr = encode([(r.title + " " + r.snippet[:200]) for r in reranked],
                             multilingual=multilingual)
        final = mmr_select(reranked, emb_for_mmr, limit)
    else:
        final = reranked[:limit]

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
    }
