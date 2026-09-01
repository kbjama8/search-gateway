"""Hacker News source — Algolia search API (stories + comments).

Contract (live-verified 2026-09-01, research report):
  GET https://hn.algolia.com/api/v1/search         (relevance-sorted)
  GET https://hn.algolia.com/api/v1/search_by_date (newest-first)
  params: query, tags (story/comment/...), numericFilters (points, created_at_i),
          hitsPerPage (max 1000). No auth; 10k req/hr/IP; 1,000-result ceiling.
"""

from __future__ import annotations

from ..extract.http import HttpError, get_json, request
from ..models import Result
from .base import Source, SourceError


class HackerNewsSource(Source):
    name = "hackernews"
    description = "Hacker News stories & discussions (Algolia API)."
    source_type = "forum"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        url = "https://hn.algolia.com/api/v1/search"
        params = {
            "query": query,
            "tags": "story",
            # signal over noise: stories with real engagement only
            "numericFilters": "points>10",
            "hitsPerPage": min(limit * 3, 60),
        }
        try:
            payload = await get_json(url, source="hackernews", params=params,
                                     timeout=12.0)
        except HttpError as exc:
            raise SourceError(f"hackernews request failed: {exc}") from exc

        results: list[Result] = []
        for hit in payload.get("hits", []):
            title = (hit.get("title") or hit.get("story_title") or "").strip()
            if not title:
                continue
            oid = hit.get("objectID") or hit.get("story_id")
            url = (hit.get("url") or
                   (f"https://news.ycombinator.com/item?id={oid}" if oid else ""))
            results.append(Result(
                title=title[:200],
                url=url,
                snippet=(f"{hit.get('points', 0)} points · "
                         f"{hit.get('num_comments', 0)} comments"),
                source=self.name,
                engine="algolia",
                published=hit.get("created_at"),
                meta={
                    "points": hit.get("points"),
                    "num_comments": hit.get("num_comments"),
                    "author": hit.get("author"),
                },
            ))
            if len(results) >= limit:
                break
        return results

    async def available(self) -> tuple[bool, str]:
        try:
            r = await request("GET",
                              "https://hn.algolia.com/api/v1/search?query=test&hitsPerPage=1",
                              source="hackernews", timeout=8.0)
            return r.status_code == 200, f"http {r.status_code}"
        except HttpError as exc:
            return False, str(exc)
