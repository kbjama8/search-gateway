"""HTTP facade with optional TLS/JA3 impersonation.

Default path is httpx (current behavior). With SEARCH_GATEWAY_IMPERSONATE=1,
requests to fingerprinted platforms (bilibili/zhihu/weibo) go through
curl_cffi impersonating a real Chrome fingerprint — TLS/JA3/HTTP2 included
(LESSONS.md §5.5). Self-hosted and pure-API sources never impersonate.

Both paths return the same minimal response shape, so callers never branch.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace  # noqa: F401 — convenience for callers
from typing import Any

from ..config import IMPERSONATE, IMPERSONATE_SOURCES
from .egress import assert_egress

logger = logging.getLogger("search_gateway.extract.http")


_SENTINEL = object()


class Response:
    """Minimal httpx/curl_cffi-compatible response wrapper."""

    def __init__(self, status_code: int, headers: dict[str, str], text: str,
                 payload: Any = _SENTINEL):
        self.status_code = status_code
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.text = text
        self._payload = payload

    def json(self) -> Any:
        if self._payload is not _SENTINEL:
            return self._payload
        return json.loads(self.text)

    def raise_for_status(self) -> Response:
        if self.status_code >= 400:
            raise HTTPStatusError(self.status_code)
        return self


class HTTPStatusError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"http {status_code}")
        self.status_code = status_code


def _should_impersonate(source: str | None) -> bool:
    return bool(IMPERSONATE and source and source in IMPERSONATE_SOURCES)


async def request(method: str, url: str, *, source: str | None = None,
                  headers: dict[str, str] | None = None,
                  params: dict[str, Any] | None = None,
                  timeout: float = 20.0) -> Response:
    """Perform a GET/POST; impersonate when flagged and curl_cffi is present.

    curl_cffi failure degrades to httpx rather than raising — the extraction
    layer never lets a transport enhancement sink a request.

    The L1 egress floor is checked before every call (pre-nav; the API tier
    does not follow redirects, so there is no post-redirect surface here —
    see web.py for the reader stages).
    """
    assert_egress(url, source)
    if _should_impersonate(source):
        try:
            return await _curl_cffi_request(method, url, headers=headers,
                                            params=params, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 — degrade to httpx
            logger.debug("curl_cffi request degraded to httpx: %s", exc)
    return await _httpx_request(method, url, headers=headers, params=params,
                                timeout=timeout)


async def _httpx_request(method: str, url: str, *, headers, params,
                         timeout: float) -> Response:
    import httpx
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.request(method, url, headers=headers, params=params)
        return Response(r.status_code, dict(r.headers), r.text, r.json())


async def _curl_cffi_request(method: str, url: str, *, headers, params,
                             timeout: float) -> Response:
    from curl_cffi.requests import AsyncSession
    async with AsyncSession(impersonate="chrome") as session:
        r = await session.request(method, url, headers=headers, params=params,
                                  timeout=timeout)
        return Response(r.status_code, dict(r.headers), r.text, r.json())


async def get_json(url: str, *, source: str | None = None,
                   headers: dict[str, str] | None = None,
                   params: dict[str, Any] | None = None,
                   timeout: float = 20.0) -> Any:
    r = await request("GET", url, source=source, headers=headers,
                      params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()
