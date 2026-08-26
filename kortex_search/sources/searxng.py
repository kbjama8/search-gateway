"""SearXNG metasearch source (JSON API)."""

from __future__ import annotations

from ..config import SEARXNG_BASE
from ..extract.http import HttpError, get_json, request
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
        headers = {"User-Agent": "kortex-search/0.1"}
        try:
            data = await get_json(url, source="searxng", params=params,
                                  headers=headers, timeout=15.0)
        except HttpError as exc:
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
            r = await request("GET", f"{SEARXNG_BASE}/healthz",
                              source="searxng", timeout=5.0)
            return (r.status_code == 200 and r.text.strip() == "OK",
                    r.text.strip())
        except HttpError as exc:
            return False, str(exc)
