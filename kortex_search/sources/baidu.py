"""Baidu hot search — top.baidu.com public board (no auth).

Public JSON endpoint (`top.baidu.com/api/board?platform=wise&tab=realtime`),
no login required — a free win for Chinese-ecosystem timeliness
(LESSONS.md §3.6). Search semantics: the realtime board, optionally filtered
by the query; an empty query returns the top of the board.

Shape history (dual-shape parser, PHASE8/0.4.3):
  legacy (pre-2026)  data.cards[] = [{word, hotScore, index, url, ...}]
  current (2026)     data.cards[] = [{component:"tabTextList",
                       content:[{content:[{isTop, index, url, word, hotTag,
                       newHotName, ...}, ...]}]}]

Doctrine guard: a 200 response whose JSON has `cards` but yields ZERO
parseable items in either shape is a SHAPE DRIFT, not an empty board — it
raises SourceError so doctor/envelope name the state instead of silently
returning `[]` (the failure mode R12 caught).
"""

from __future__ import annotations

import logging
import re

from ..config import CN_SOURCES
from ..extract.http import get_json
from ..models import Result
from .base import Source, SourceError

logger = logging.getLogger("kortex_search.sources.baidu")

_BOARD = "https://top.baidu.com/api/board"
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/121.0 Safari/537.36")


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _int_or(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_legacy_shape(cards: list) -> list[dict]:
    """pre-2026 shape: cards[] carry word/hotScore directly."""
    out: list[dict] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        word = str(card.get("word") or _strip_tags(card.get("content") or ""))
        if not word:
            continue
        out.append({
            "word": word,
            "url": card.get("url") or "",
            "rank": _int_or(card.get("index")),
            "heat": card.get("hotScore"),
            "is_hot": bool(card.get("is_hot")),
            "is_new": bool(card.get("is_new")),
            "category": card.get("category"),
            "pinned": False,
        })
    return out


def _parse_current_shape(cards: list) -> list[dict]:
    """2026 tabTextList shape: cards[].content[].content[] items."""
    out: list[dict] = []
    for card in cards:
        if not isinstance(card, dict) or card.get("component") != "tabTextList":
            continue
        for entry in card.get("content") or []:
            if not isinstance(entry, dict):
                continue
            for item in entry.get("content") or []:
                if not isinstance(item, dict):
                    continue
                word = str(item.get("word") or "").strip()
                if not word:
                    continue
                hot_name = str(item.get("newHotName") or "")
                out.append({
                    "word": word,
                    "url": item.get("url") or "",
                    "rank": _int_or(item.get("index")),
                    "heat": item.get("hotTag"),  # heat bucket string ("3")
                    "is_hot": hot_name == "热" or bool(item.get("is_hot")),
                    "is_new": hot_name == "新" or bool(item.get("is_new")),
                    "category": None,
                    "pinned": str(item.get("isTop")).lower() == "true"
                              or item.get("isTop") is True,
                })
    return out


def _parse_board(data: dict) -> tuple[list[dict], bool]:
    """Parse both shapes. Returns (items, shape_recognized).

    `shape_recognized=False` means the response contained `cards` but no
    parseable items in either shape — callers must treat that as drift, not
    emptiness.
    """
    cards = (data.get("data") or {}).get("cards")
    if cards is None:
        return [], False
    if not isinstance(cards, list):
        return [], False
    if not cards:
        return [], True  # legitimately empty board
    items = _parse_current_shape(cards)
    if items:
        return items, True
    items = _parse_legacy_shape(cards)
    return items, bool(items)


class BaiduSource(Source):
    name = "baidu"
    description = "Baidu hot search board (public, no auth)."
    source_type = "web"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        if not CN_SOURCES:
            raise SourceError(
                "disabled (KORTEX_SEARCH_CN_SOURCES=0) — baidu is opt-in")
        params = {"platform": "wise", "tab": "realtime"}
        headers = {"User-Agent": _UA}
        try:
            data = await get_json(_BOARD, source="baidu", params=params,
                                  headers=headers)
        except Exception as exc:
            raise SourceError(f"baidu board failed: {exc}") from exc

        items, shape_ok = _parse_board(data)
        if not shape_ok:
            raise SourceError(
                "baidu board shape drift: cards present but unparseable "
                "(endpoint structure changed — record a fixture and update "
                "the parser)")

        q = query.strip().lower()
        out: list[Result] = []
        for it in items:
            word = it["word"]
            if q and q not in word.lower():
                continue
            out.append(Result(
                title=word[:140],
                url=it["url"] or ("https://www.baidu.com/s?wd=" + _quote(word)),
                snippet=f"热度 {it['heat'] or ''}".strip(),
                source=self.name, engine="baidu-board",
                meta={"rank": it["rank"], "heat": it["heat"],
                      "category": it["category"],
                      "is_new": it["is_new"], "is_hot": it["is_hot"],
                      "pinned": it["pinned"]},
            ))
            if len(out) >= limit:
                break
        return out

    async def available(self) -> tuple[bool, str]:
        if not CN_SOURCES:
            return False, "disabled (KORTEX_SEARCH_CN_SOURCES=0)"
        try:
            out = await self.search("", limit=1)
            return True, f"ok ({len(out)} items)"
        except SourceError as exc:
            return False, str(exc)


def _quote(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(s)
