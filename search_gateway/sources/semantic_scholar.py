# -*- coding: utf-8 -*-
"""Semantic Scholar academic source (free; optional fallback, rate-limited)."""

from __future__ import annotations

import asyncio

import httpx

from ..models import Result
from .base import Source, SourceError

_FIELDS = ("title,abstract,year,venue,externalIds,authors,citationCount,"
           "openAccessPdf,publicationTypes")


class SemanticScholarSource(Source):
    name = "semantic_scholar"
    description = "Semantic Scholar search (free, optional fallback)."
    source_type = "paper"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {"query": query, "limit": limit, "fields": _FIELDS}
        data = await self._get_json(url, params)
        return [self._to_result(p) for p in data.get("data", []) if p.get("title")]

    async def citations(self, identifier: str, limit: int = 20) -> list[Result]:
        url = f"https://api.semanticscholar.org/graph/v1/paper/{self._paper_id(identifier)}/citations"
        params = {"limit": limit, "fields": _FIELDS}
        data = await self._get_json(url, params)
        return [self._to_result(c.get("citingPaper", {})) for c in data.get("data", [])
                if c.get("citingPaper", {}).get("title")]

    async def references(self, identifier: str, limit: int = 20) -> list[Result]:
        url = f"https://api.semanticscholar.org/graph/v1/paper/{self._paper_id(identifier)}/references"
        params = {"limit": limit, "fields": _FIELDS}
        data = await self._get_json(url, params)
        return [self._to_result(c.get("citedPaper", {})) for c in data.get("data", [])
                if c.get("citedPaper", {}).get("title")]

    @staticmethod
    def _paper_id(identifier: str) -> str:
        s = identifier.strip()
        if s.startswith("10.") or "doi.org/" in s:
            return "DOI:" + s.replace("https://doi.org/", "").replace("http://doi.org/", "")
        if s.lower().startswith("arxiv:"):
            return "arXiv:" + s.split(":", 1)[1].strip()
        return "arXiv:" + s

    async def _get_json(self, url: str, params: dict, retries: int = 3) -> dict:
        """GET with retry/backoff — S2 is 429-prone without a key."""
        last: Exception | None = None
        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.get(url, params=params)
                    if resp.status_code == 429:
                        last = SourceError("semantic scholar rate-limited (429)")
                        await asyncio.sleep(2 * (attempt + 1))
                        continue
                    resp.raise_for_status()
                    return resp.json()
            except httpx.HTTPError as exc:
                last = exc
                await asyncio.sleep(1 + attempt)
        raise SourceError(f"semantic scholar failed: {last}")

    @staticmethod
    def _to_result(p: dict) -> Result:
        ext = p.get("externalIds") or {}
        authors = [a.get("name", "") for a in (p.get("authors") or [])]
        pdf = p.get("openAccessPdf") or {}
        return Result(
            title=p.get("title") or "",
            url=p.get("url") or pdf.get("url") or "",
            snippet=(p.get("abstract") or "")[:800],
            source="semantic_scholar",
            engine="semantic-scholar",
            published=f"{p.get('year')}" if p.get("year") else None,
            meta={
                "doi": ext.get("DOI"),
                "arxiv_id": ext.get("ArXiv"),
                "paper_id": p.get("paperId"),
                "authors": authors,
                "year": p.get("year"),
                "venue": p.get("venue"),
                "citation_count": p.get("citationCount"),
                "is_oa": bool(p.get("openAccessPdf")),
                "pdf_url": pdf.get("url"),
                "abstract": p.get("abstract"),
            },
        )

    async def available(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get("https://api.semanticscholar.org/graph/v1/paper/search",
                                     params={"query": "test", "limit": 1, "fields": "title"})
                return r.status_code == 200, f"http {r.status_code}"
        except httpx.HTTPError as exc:
            return False, str(exc)
