"""Zhihu hot list — 知乎热榜 via the anonymous public endpoint.

`api.zhihu.com/topstory/hot-list` answers HTTP 200 with **no cookie** (R11,
verified live 2026-08-23; LESSONS.md §3.7 noted only the cookie-gated v4
search API — the hot list is the zero-cookie complement). Capped at 30 items
by the endpoint regardless of `limit`. No heat field is returned — rank is
the heat proxy.

Gated by SEARCH_GATEWAY_CN_SOURCES like the rest of the CN tier. A 200
response with `data` present but zero parseable items is a shape drift and
raises SourceError — never a silent empty.
"""

from __future__ import annotations

import logging

from ..config import CN_SOURCES
from ..extract.http import get_json
from ..models import Result
from .base import Source, SourceError

logger = logging.getLogger("search_gateway.sources.zhihu_hot")

_ENDPOINT = "https://api.zhihu.com/topstory/hot-list"
_MAX_ITEMS = 30  # hard cap enforced by the endpoint
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/121.0 Safari/537.36")


class ZhihuHotSource(Source):
    name = "zhihu_hot"
    description = "Zhihu hot list (anonymous, no cookie)."
    source_type = "forum"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        if not CN_SOURCES:
            raise SourceError(
                "disabled (SEARCH_GATEWAY_CN_SOURCES=0) — zhihu_hot is opt-in")
        params = {"limit": min(limit, _MAX_ITEMS)}
        headers = {
            "User-Agent": _UA,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.zhihu.com/hot",
            "x-requested-with": "fetch",
        }
        try:
            data = await get_json(_ENDPOINT, source="zhihu_hot",
                                  params=params, headers=headers)
        except Exception as exc:
            raise SourceError(f"zhihu hot-list request failed: {exc}") from exc

        items = data.get("data") or []
        if not isinstance(items, list):
            raise SourceError(
                "zhihu hot-list shape drift: 'data' present but not a list "
                "(record a fixture and update the parser)")

        q = query.strip().lower()
        out: list[Result] = []
        for rank, item in enumerate(items, 1):
            if not isinstance(item, dict):
                continue
            target = item.get("target") or {}
            title = str(target.get("title") or "").strip()
            if not title:
                continue
            if q and q not in title.lower():
                continue
            r = self._to_result(target, rank)
            if r is not None:
                out.append(r)
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _to_result(target: dict, rank: int) -> Result | None:
        title = str(target.get("title") or "").strip()
        qid = target.get("id")
        # the API returns api.zhihu.com URLs — rewrite to the human surface
        url = (f"https://www.zhihu.com/question/{qid}" if qid else "")
        if not title and not url:
            return None
        created = target.get("created")
        return Result(
            title=title[:140],
            url=url,
            snippet=str(target.get("excerpt") or "")[:600],
            source="zhihu_hot", engine="zhihu-hot",
            published=f"{created}" if created else None,
            meta={
                "rank": rank,
                "answer_count": target.get("answer_count"),
                "follower_count": target.get("follower_count"),
            },
        )

    async def available(self) -> tuple[bool, str]:
        if not CN_SOURCES:
            return False, "disabled (SEARCH_GATEWAY_CN_SOURCES=0)"
        try:
            out = await self.search("", limit=1)
            return True, f"ok ({len(out)} items)"
        except SourceError as exc:
            return False, str(exc)
