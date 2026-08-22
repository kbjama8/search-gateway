"""SearXNG metasearch source (JSON API)."""

from __future__ import annotations

import httpx

from ..config import SEARXNG_BASE
from ..models import Result
from .base import Source, SourceError


class SearXNGSource(Source):
    name = "searxng"
    description = "Self-hosted metasearch (bing/duckduckgo/brave/... + science/news)."

    async def search(self, query: str, limit: int = 10, category: str = "general",
                     freshness: str | None = None) -> list[Result]:
        url = f"{SEARXNG_BASE}/search"
        params = {"q": query, "format": "json", "categories": category}
        if freshness:
            params["time_range"] = freshness
        headers = {"User-Agent": "search-gateway/0.1"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise SourceError(f"searxng request failed: {exc}") from exc

        results: list[Result] = []
        for item in data.get("results", [])[:limit]:
            results.append(Result(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
                source=self.name,
                engine=item.get("engine", "searxng"),
                published=item.get("publishedDate") or None,
                meta={
                    "category": item.get("category", ""),
                    "engines": item.get("engines", []),
                },
            ))
        return results

    async def available(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{SEARXNG_BASE}/healthz")
                return r.status_code == 200 and r.text.strip() == "OK", r.text.strip()
        except httpx.HTTPError as exc:
            return False, str(exc)
