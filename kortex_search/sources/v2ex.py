"""V2EX source — sov2ex search API (V2EX's community search)."""

from __future__ import annotations

from ..extract.http import HttpError, get_json, request
from ..models import Result
from .base import Source, SourceError, normalize_published


class V2EXSource(Source):
    name = "v2ex"
    description = "V2EX community search (sov2ex API)."
    source_type = "forum"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        url = "https://www.sov2ex.com/api/search"
        try:
            payload = await get_json(
                url, source="v2ex", params={"q": query, "size": limit},
                headers={"User-Agent": "kortex-search/0.1"}, timeout=15.0)
        except HttpError as exc:
            raise SourceError(f"v2ex request failed: {exc}") from exc

        results: list[Result] = []
        for hit in payload.get("hits", []):
            src = hit.get("_source") or {}
            tid = src.get("id")
            title = src.get("title", "")
            results.append(Result(
                title=title[:140],
                url=f"https://www.v2ex.com/t/{tid}" if tid else "",
                snippet=(src.get("content") or "")[:600],
                source=self.name,
                engine="sov2ex",
                published=normalize_published(src.get("created")),
                meta={
                    "member": src.get("member"),
                    "replies": src.get("replies"),
                },
            ))
            if len(results) >= limit:
                break
        return results

    async def available(self) -> tuple[bool, str]:
        try:
            r = await request("GET", "https://www.sov2ex.com/api/search",
                              source="v2ex", params={"q": "test", "size": 1},
                              headers={"User-Agent": "Mozilla/5.0"}, timeout=8.0)
            return r.status_code == 200, f"http {r.status_code}"
        except HttpError as exc:
            return False, str(exc)
