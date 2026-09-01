"""Wikipedia source — MediaWiki CirrusSearch (full-text, no auth).

Contract (live-verified 2026-09-01, research report):
  GET https://en.wikipedia.org/w/api.php?action=query&list=search
      &srsearch=<query>&srlimit=<1..500>&format=json
Response: query.search[] = {title, snippet (HTML with <span class=searchmatch>),
timestamp, wordcount, ...}. A descriptive User-Agent is REQUIRED etiquette
(MediaWiki IP-blocks UA-less scripts).
"""

from __future__ import annotations

import re
from urllib.parse import quote

from ..extract.http import HttpError, get_json, request
from ..models import Result
from .base import Source, SourceError

_UA = "kortex-search/0.7 (https://github.com/kbjama8/kortex-search)"
_TAG_RE = re.compile(r"<[^>]+>")


class WikipediaSource(Source):
    name = "wikipedia"
    description = "Wikipedia full-text search (MediaWiki API)."
    source_type = "doc"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": min(limit * 2, 50),
            "format": "json",
        }
        try:
            payload = await get_json(url, source="wikipedia", params=params,
                                     headers={"User-Agent": _UA}, timeout=12.0)
        except HttpError as exc:
            raise SourceError(f"wikipedia request failed: {exc}") from exc

        results: list[Result] = []
        for hit in payload.get("query", {}).get("search", []):
            title = (hit.get("title") or "").strip()
            if not title:
                continue
            snippet = _TAG_RE.sub("", hit.get("snippet") or "").strip()
            results.append(Result(
                title=title[:200],
                # quote(): titles can carry / ? # — never interpolate raw
                # into a URL path (identifier-injection lesson)
                url=f"https://en.wikipedia.org/wiki/{quote(title, safe='')}",
                snippet=snippet[:600],
                source=self.name,
                engine="cirrussearch",
                published=hit.get("timestamp"),
                meta={
                    "wordcount": hit.get("wordcount"),
                    "pageid": hit.get("pageid"),
                },
            ))
            if len(results) >= limit:
                break
        return results

    async def available(self) -> tuple[bool, str]:
        try:
            r = await request("GET", "https://en.wikipedia.org/w/api.php",
                              source="wikipedia",
                              params={"action": "query", "list": "search",
                                      "srsearch": "test", "srlimit": 1,
                                      "format": "json"},
                              headers={"User-Agent": _UA}, timeout=8.0)
            return r.status_code == 200, f"http {r.status_code}"
        except HttpError as exc:
            return False, str(exc)
