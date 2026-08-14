# -*- coding: utf-8 -*-
"""Web page reader via Jina Reader (read_url, not part of search fan-out)."""

from __future__ import annotations

import httpx

from .base import Source, SourceError


class WebSource(Source):
    name = "web"
    description = "Read any web page as Markdown (Jina Reader)."

    async def search(self, query: str, limit: int = 10) -> list:
        # web is a reader, not a searcher — never called by the fan-out.
        return []

    async def read(self, url: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(f"https://r.jina.ai/{url}")
                resp.raise_for_status()
                text = resp.text
        except httpx.HTTPError as exc:
            raise SourceError(f"jina read failed: {exc}")
        return text[:20000]
