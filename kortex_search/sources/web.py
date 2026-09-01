"""Web page reader — multi-stage content extraction (read_url).

Stage order (configurable via KORTEX_SEARCH_READ_URL_STAGES, default
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
from urllib.parse import quote

import httpx

from ..config import READ_URL_STAGES
from ..extract.egress import assert_egress
from ..extract.proxies import jina_header
from .base import Source, SourceError

logger = logging.getLogger("kortex_search.sources.web")

_MIN_USABLE = 50
_CAP = 20000

# Scrape-tier shared pools (sweep 2026-08-31): redirect-following stages
# reuse per-origin keep-alive connections too; the per-hop SSRF guard is
# registered at construction (event_hooks are client-level). Async for the
# jina stage, sync for readability's to_thread fetch. Reset by the conftest
# autouse fixture; closed by the graceful-shutdown paths.
_scrape: httpx.AsyncClient | None = None
_scrape_sync: httpx.Client | None = None

_SCRAPE_TIMEOUT = httpx.Timeout(30.0, connect=5.0, pool=2.0)
_SCRAPE_LIMITS = httpx.Limits(max_connections=50,
                              max_keepalive_connections=10,
                              keepalive_expiry=60.0)


def _get_scrape_client() -> httpx.AsyncClient:
    global _scrape
    if _scrape is None or getattr(_scrape, "is_closed", False):
        _scrape = httpx.AsyncClient(timeout=_SCRAPE_TIMEOUT,
                                    limits=_SCRAPE_LIMITS,
                                    follow_redirects=True,
                                    trust_env=False,
                                    event_hooks={"request": [_hop_guard]})
    return _scrape


def _get_scrape_sync() -> httpx.Client:
    global _scrape_sync
    if _scrape_sync is None or getattr(_scrape_sync, "is_closed", False):
        _scrape_sync = httpx.Client(timeout=_SCRAPE_TIMEOUT,
                                    limits=_SCRAPE_LIMITS,
                                    follow_redirects=True,
                                    trust_env=False,
                                    event_hooks={"request": [_hop_guard]})
    return _scrape_sync


async def aclose() -> None:
    global _scrape, _scrape_sync
    if _scrape is not None and not _scrape.is_closed:
        await _scrape.aclose()
    _scrape = None
    if _scrape_sync is not None and not _scrape_sync.is_closed:
        _scrape_sync.close()  # noqa: ASYNC212 — sync Client closes synchronously
    _scrape_sync = None


def _jina_url(target: str) -> str:
    """Compose the r.jina.ai request for `target`.

    The target is percent-encoded so it stays ONE path segment of OUR
    request — an unencoded URL smuggles delimiters (`//`, `?`, `#`, `@`)
    into our request line and can shift what Jina (or our own client)
    resolves. Jina decodes it server-side (their docs: "don't forget to
    encode the URL").
    """
    return f"https://r.jina.ai/{quote(target, safe='')}"


def _hop_guard(request) -> None:
    """Per-hop SSRF re-validation (httpx `request` event hook).

    httpx fires request hooks for every redirect hop BEFORE the connection
    is made (>=0.19); raising aborts the chain. Every hop must stay on
    http(s) and pass the egress floor — a redirect can jump from a public
    page to a private/metadata host (LESSONS.md §1.5, hermes-agent
    PR #21228).
    """
    scheme = (getattr(request.url, "scheme", "") or "").lower()
    if scheme not in ("http", "https"):
        raise SourceError(
            f"blocked (egress-floor/scheme {scheme!r}): non-http(s) redirect hop")
    assert_egress(str(request.url), "web")


class WebSource(Source):
    name = "web"
    description = "Read any web page as Markdown (Jina → Trafilatura → Readability)."

    async def search(self, query: str, limit: int = 10) -> list:
        # web is a reader, not a searcher — never called by the fan-out.
        return []

    async def read(self, url: str) -> str:
        # L1 floor, pre-nav: the target of every stage is checked once here;
        # each stage additionally re-checks where it can see a redirect
        # (readability below — the direct-fetch stages).
        assert_egress(url, "web")
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
        assert_egress(url, "web")
        headers = {}
        proxy = jina_header()
        if proxy:
            headers["X-Proxy-Url"] = proxy
        client = _get_scrape_client()
        resp = await client.get(_jina_url(url), headers=headers)
        resp.raise_for_status()
        return resp.text

    async def _read_trafilatura(self, url: str) -> str:
        # pre-nav only: trafilatura's own fetcher exposes no final URL —
        # the kernel layer catches redirect targets the floor can't see.
        assert_egress(url, "web")

        def _sync() -> str:
            import trafilatura
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                return ""
            return trafilatura.extract(downloaded, include_comments=False,
                                       include_tables=True) or ""
        return await asyncio.to_thread(_sync)

    async def _read_readability(self, url: str) -> str:
        assert_egress(url, "web")

        def _sync() -> str:
            from lxml import html as lxml_html
            from readability import Document
            # per-hop guard: every redirect hop passes the floor BEFORE the
            # connection is made (stronger than the old post-hoc final-URL
            # check, which let intermediate private hops connect first)
            client = _get_scrape_sync()
            resp = client.get(url)
            resp.raise_for_status()
            doc = Document(resp.text)
            summary = doc.summary()
            if not summary:
                return ""
            return " ".join(
                lxml_html.fromstring(summary).text_content().split())
        return await asyncio.to_thread(_sync)
