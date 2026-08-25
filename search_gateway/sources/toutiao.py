"""Toutiao hot search — public hot-board JSON (no auth).

Free win alongside Baidu for Chinese-ecosystem timeliness (LESSONS.md §3.6).
Search semantics: the hot board, optionally filtered by the query; an empty
query returns the top of the board.
"""

from __future__ import annotations

import logging

from ..config import CN_SOURCES
from ..extract.http import get_json
from ..models import Result
from .base import Source, SourceError

logger = logging.getLogger("search_gateway.sources.toutiao")

_BOARD = "https://www.toutiao.com/hot-event/hot-board/"
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/121.0 Safari/537.36")


class ToutiaoSource(Source):
    name = "toutiao"
    description = "Toutiao hot search board (public, no auth)."
    source_type = "news"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        if not CN_SOURCES:
            raise SourceError(
                "disabled (SEARCH_GATEWAY_CN_SOURCES=0) — toutiao is opt-in")
        params = {"origin": "toutiao_pc"}
        headers = {"User-Agent": _UA,
                   "Referer": "https://www.toutiao.com/hot"}
        try:
            data = await get_json(_BOARD, source="toutiao", params=params,
                                  headers=headers)
        except Exception as exc:
            raise SourceError(f"toutiao board failed: {exc}") from exc

        items = data.get("data") or []
        q = query.strip().lower()
        out: list[Result] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            title = str(it.get("Title") or "")
            if not title:
                continue
            if q and q not in title.lower():
                continue
            out.append(Result(
                title=title[:140],
                url=str(it.get("Url") or ""),
                snippet=it.get("Label") or "",
                source=self.name, engine="toutiao-board",
                meta={"heat": it.get("HotValue"),
                      "category": it.get("Category"),
                      "rank": it.get("Index"),
                      "is_new": it.get("Label") == "新",
                      "is_hot": it.get("Label") == "热"},
            ))
            if len(out) >= limit:
                break
        return out

    async def available(self) -> tuple[bool, str]:
        if not CN_SOURCES:
            return False, "disabled (SEARCH_GATEWAY_CN_SOURCES=0)"
        try:
            out = await self.search("", limit=1)
            return True, f"ok ({len(out)} items)"
        except SourceError as exc:
            return False, str(exc)
