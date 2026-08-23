"""Web page reader — multi-stage content extraction (read_url).

Stage order (configurable via SEARCH_GATEWAY_READ_URL_STAGES, default
`jina,trafilatura,readability`):

  1. jina        r.jina.ai — best SPA/JS rendering (LESSONS.md §4.1); carries
                 X-Proxy-Url when the proxy tier is enabled
  2. trafilatura local, zero cost, best precision (F1 0.937 / prec 0.978) on
                 server-rendered prose
  3. readability  Firefox Reader View algorithm — best recall (0.929)

Each stage runs until one returns a usable body (≥50 chars); failures log and
fall through. Every path is capped to keep the envelope bounded.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from ..config import READ_URL_STAGES
from ..extract.proxies import jina_header
from .base import Source, SourceError

logger = logging.getLogger("search_gateway.sources.web")

_MIN_USABLE = 50
_CAP = 20000


class WebSource(Source):
    name = "web"
    description = "Read any web page as Markdown (Jina → Trafilatura → Readability)."

    async def search(self, query: str, limit: int = 10) -> list:
        # web is a reader, not a searcher — never called by the fan-out.
        return []

    async def read(self, url: str) -> str:
        errors: list[str] = []
        for stage in [s.strip() for s in READ_URL_STAGES.split(",") if s.strip()]:
            handler = getattr(self, f"_read_{stage}", None)
            if handler is None:
                logger.warning("unknown read_url stage %r skipped", stage)
                continue
            try:
                text = await handler(url)
            except Exception as exc:  # noqa: BLE001 — fall through stages
                errors.append(f"{stage}: {exc}")
                continue
            if text and len(text) >= _MIN_USABLE:
                logger.debug("read_url stage=%s url=%s len=%d",
                             stage, url, len(text))
                return text[:_CAP]
            errors.append(f"{stage}: unusable body ({len(text or '')} chars)")
        raise SourceError("all read stages failed: " + "; ".join(errors))

    async def _read_jina(self, url: str) -> str:
        headers = {}
        proxy = jina_header()
        if proxy:
            headers["X-Proxy-Url"] = proxy
        async with httpx.AsyncClient(timeout=30.0,
                                     follow_redirects=True) as client:
            resp = await client.get(f"https://r.jina.ai/{url}", headers=headers)
            resp.raise_for_status()
            return resp.text

    async def _read_trafilatura(self, url: str) -> str:
        def _sync() -> str:
            import trafilatura
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                return ""
            return trafilatura.extract(downloaded, include_comments=False,
                                       include_tables=True) or ""
        return await asyncio.to_thread(_sync)

    async def _read_readability(self, url: str) -> str:
        def _sync() -> str:
            import httpx as _httpx
            from lxml import html as lxml_html
            from readability import Document
            resp = _httpx.get(url, timeout=30.0, follow_redirects=True)
            resp.raise_for_status()
            doc = Document(resp.text)
            summary = doc.summary()
            if not summary:
                return ""
            return " ".join(lxml_html.fromstring(summary).text_content().split())
        return await asyncio.to_thread(_sync)
