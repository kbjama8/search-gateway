"""Baidu hot search — top.baidu.com public board (no auth).

Public JSON endpoint (`top.baidu.com/api/board?platform=wise&tab=realtime`),
no login required — a free win for Chinese-ecosystem timeliness
(LESSONS.md §3.6). Search semantics: the realtime board, optionally filtered
by the query; an empty query returns the top of the board.
"""

from __future__ import annotations

import logging
import re

from ..config import CN_SOURCES
from ..extract.http import get_json
from ..models import Result
from .base import Source, SourceError

logger = logging.getLogger("search_gateway.sources.baidu")

_BOARD = "https://top.baidu.com/api/board"
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/121.0 Safari/537.36")


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


class BaiduSource(Source):
    name = "baidu"
    description = "Baidu hot search board (public, no auth)."
    source_type = "web"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        if not CN_SOURCES:
            raise SourceError(
                "disabled (SEARCH_GATEWAY_CN_SOURCES=0) — baidu is opt-in")
        params = {"platform": "wise", "tab": "realtime"}
        headers = {"User-Agent": _UA}
        try:
            data = await get_json(_BOARD, source="baidu", params=params,
                                  headers=headers)
        except Exception as exc:
            raise SourceError(f"baidu board failed: {exc}") from exc

        cards = ((data.get("data") or {}).get("cards") or [])
        q = query.strip().lower()
        out: list[Result] = []
        for card in cards:
            if not isinstance(card, dict):
                continue
            word = str(card.get("word") or
                       _strip_tags(card.get("content") or ""))
            if not word:
                continue
            if q and q not in word.lower():
                continue
            url = card.get("url") or (
                "https://www.baidu.com/s?wd=" +
                _quote(word) if word else "")
            out.append(Result(
                title=word[:140], url=url,
                snippet=f"热度 {card.get('hotScore') or ''}",
                source=self.name, engine="baidu-board",
                meta={"rank": card.get("index"),
                      "heat": card.get("hotScore"),
                      "category": card.get("category"),
                      "is_new": card.get("is_new"),
                      "is_hot": card.get("is_hot")},
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


def _quote(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(s)
