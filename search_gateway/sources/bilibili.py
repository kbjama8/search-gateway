# -*- coding: utf-8 -*-
"""Bilibili source — B站 search API (no login required)."""

from __future__ import annotations

import httpx

from ..models import Result
from .base import Source, SourceError


class BilibiliSource(Source):
    name = "bilibili"
    description = "Bilibili search (B站 API)."
    source_type = "video"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        url = "https://api.bilibili.com/x/web-interface/search/all/v2"
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com",
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params={"keyword": query}, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            raise SourceError(f"bilibili request failed: {exc}")

        code = payload.get("code")
        if code != 0:
            raise SourceError(f"bilibili API code {code}: {payload.get('message', '')}")

        results: list[Result] = []
        for block in payload.get("data", {}).get("result", []):
            rtype = block.get("result_type", "")
            items = block.get("data") or []
            if not isinstance(items, list):
                continue
            for it in items:
                if not isinstance(it, dict):
                    continue
                title = (it.get("title") or "").replace('<em class="keyword">', "").replace("</em>", "")
                if not title:
                    continue
                url = it.get("arcurl") or it.get("url") or ""
                results.append(Result(
                    title=title[:140],
                    url=url,
                    snippet=(it.get("description") or "")[:600],
                    source=self.name,
                    engine="bilibili-api",
                    published=None,
                    meta={
                        "type": rtype,
                        "author": it.get("author"),
                        "play": it.get("play"),
                    },
                ))
                if len(results) >= limit:
                    return results
        return results

    async def available(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get("https://api.bilibili.com/x/web-interface/search/all/v2",
                                     params={"keyword": "test"}, headers={"User-Agent": "Mozilla/5.0"})
                return r.status_code == 200, f"http {r.status_code}"
        except httpx.HTTPError as exc:
            return False, str(exc)
