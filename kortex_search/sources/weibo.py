"""Weibo source — 微博 hot search + keyword search (cookie-gated).

The public hot-search endpoint (`weibo.com/ajax/side/hotSearch`) needs no
login but validates a mobile User-Agent and a visitor cookie
(LESSONS.md §3.8). Keyword search (`/ajax/side/searchAll`) requires a
logged-in `SUB` cookie.

Degradation ladder, in order:
  1. WEIBO_SUB set            → keyword search (precise)
  2. no SUB, query matches    → hot list filtered by the query
  3. no SUB, empty query      → top of the hot list
All behind KORTEX_SEARCH_CN_SOURCES; disabled otherwise.
"""

from __future__ import annotations

import logging
import re

from ..config import CN_SOURCES, WEIBO_SUB
from ..extract.http import get_json
from ..models import Result
from .base import Source, SourceError

logger = logging.getLogger("kortex_search.sources.weibo")

_HOT = "https://weibo.com/ajax/side/hotSearch"
_SEARCH = "https://weibo.com/ajax/side/searchAll"
_UA_MOBILE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
              "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
              "Mobile/15E148 Safari/604.1")
_REFERER = "https://weibo.com/"


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


class WeiboSource(Source):
    name = "weibo"
    description = "Weibo hot search + keyword search (SUB cookie optional)."
    source_type = "post"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        if not CN_SOURCES:
            raise SourceError(
                "disabled (KORTEX_SEARCH_CN_SOURCES=0) — weibo is opt-in")
        if WEIBO_SUB:
            try:
                out = await self._keyword_search(query, limit)
            except SourceError:
                logger.warning("weibo keyword search failed; hot-list "
                               "fallback")
                out = await self._hot(limit, query)
            return out
        return await self._hot(limit, query)

    async def _keyword_search(self, query: str, limit: int) -> list[Result]:
        headers = {"User-Agent": _UA_MOBILE, "Referer": _REFERER,
                   "Cookie": WEIBO_SUB}
        try:
            data = await get_json(_SEARCH, source="weibo", headers=headers,
                                  params={"q": query})
        except Exception as exc:
            raise SourceError(f"weibo search failed: {exc}") from exc

        results: list[Result] = []
        cards = data.get("data", {}).get("cards") or []
        for card in cards:
            group = card.get("card_group") or [card]
            for c in group:
                mblog = c.get("mblog")
                if not isinstance(mblog, dict):
                    continue
                text = _strip_html(mblog.get("text") or "")
                if not text:
                    continue
                mid = mblog.get("mid")
                user = (mblog.get("user") or {}).get("screen_name")
                results.append(Result(
                    title=text[:140],
                    url=(f"https://weibo.com/{user}/{mblog.get('bid')}"
                         if user and mblog.get("bid")
                         else (f"https://weibo.com/{mid}" if mid else "")),
                    snippet=text[:600],
                    source=self.name, engine="weibo-search",
                    published=mblog.get("created_at"),
                    meta={"author": user,
                          "reposts": mblog.get("reposts_count"),
                          "comments": mblog.get("comments_count"),
                          "likes": mblog.get("attitudes_count"),
                          "engagement": {
                              "reposts": mblog.get("reposts_count"),
                              "comments": mblog.get("comments_count"),
                              "likes": mblog.get("attitudes_count")}},
                ))
                if len(results) >= limit:
                    return results
        return results

    async def _hot(self, limit: int, query: str = "") -> list[Result]:
        headers = {"User-Agent": _UA_MOBILE, "Referer": _REFERER}
        try:
            data = await get_json(_HOT, source="weibo", headers=headers)
        except Exception as exc:
            raise SourceError(f"weibo hot search failed: {exc}") from exc

        items = ((data.get("data") or {}).get("realtime") or []) \
            + ((data.get("data") or {}).get("hotgovs") or [])
        q = query.strip().lower()
        out: list[Result] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            word = str(it.get("word") or "")
            if not word:
                continue
            if q and q not in word.lower():
                continue
            url = (f"https://s.weibo.com/weibo?q={urllib_quote(word)}"
                   "&Refer=hot_search")
            out.append(Result(
                title=word[:140], url=url, snippet=f"热度 {it.get('num') or ''}",
                source=self.name, engine="weibo-hot",
                meta={"rank": it.get("rank"), "heat": it.get("num"),
                      "category": it.get("category"),
                      "is_new": it.get("is_new"), "is_hot": it.get("is_hot")},
            ))
            if len(out) >= limit:
                break
        return out


def urllib_quote(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(s)
