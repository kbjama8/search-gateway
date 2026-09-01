"""HTTP facade with optional TLS/JA3 impersonation.

Default path is httpx (current behavior). With KORTEX_SEARCH_IMPERSONATE=1,
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

import httpx

from .. import __version__
from ..config import IMPERSONATE, IMPERSONATE_SOURCES
from .egress import assert_egress

logger = logging.getLogger("kortex_search.extract.http")


_SENTINEL = object()

# Shared connection pool (sweep 2026-08-31): one client per process. The
# fan-out touches ~20 hosts per search — per-request client construction
# paid a TCP+TLS handshake on EVERY source call; a pooled client keeps
# per-origin keep-alive sockets warm (keepalive_expiry 60s vs httpx's 5s
# default). follow_redirects stays False (API tier; the scrape tier opts in
# per request with per-hop egress guards). trust_env=False: no surprise
# proxy pickup on a LAN server. Lazy-init + never closed mid-flight; tests
# reset via the conftest autouse fixture.
_client: httpx.AsyncClient | None = None

_CLIENT_TIMEOUT = httpx.Timeout(20.0, connect=5.0, pool=2.0)
_CLIENT_LIMITS = httpx.Limits(max_connections=100,
                              max_keepalive_connections=20,
                              keepalive_expiry=60.0)


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or getattr(_client, "is_closed", False):
        _client = httpx.AsyncClient(
            timeout=_CLIENT_TIMEOUT,
            limits=_CLIENT_LIMITS,
            follow_redirects=False,
            trust_env=False,
            headers={"user-agent": f"kortex-search/{__version__}"},
        )
    return _client


async def aclose() -> None:
    """Close the shared pool (graceful shutdown paths)."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


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


class HttpError(Exception):
    """Any transport/HTTP failure from the facade.

    The facade never leaks underlying httpx exceptions to callers — sources
    catch one type (bug-sweep discovery 2026-08-26: raw-httpx sources
    bypassed the floor and each caught a different exception surface).
    """


class HTTPStatusError(HttpError):
    def __init__(self, status_code: int):
        super().__init__(f"http {status_code}")
        self.status_code = status_code


def _wrap(exc: Exception) -> HttpError:
    # the message carries the underlying type; explicit `from` chaining
    # happens at the raise sites that want it
    return HttpError(f"{type(exc).__name__}: {exc}")


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
    see web.py for the reader stages). Transport failures raise HttpError.
    """
    assert_egress(url, source)
    if _should_impersonate(source):
        try:
            return await _curl_cffi_request(method, url, headers=headers,
                                            params=params, timeout=timeout)
        except HttpError:
            raise
        except Exception as exc:  # noqa: BLE001 — degrade to httpx
            logger.debug("curl_cffi request degraded to httpx: %s", exc)
    try:
        return await _httpx_request(method, url, headers=headers, params=params,
                                    timeout=timeout)
    except HttpError:
        raise
    except Exception as exc:
        raise _wrap(exc) from exc


async def _httpx_request(method: str, url: str, *, headers, params,
                         timeout: float) -> Response:
    r = await _get_client().request(method, url, headers=headers,
                                    params=params, timeout=timeout)
    # payload parsed LAZILY by Response.json() — eager parsing breaks
    # text/XML endpoints (arxiv Atom feed; live-verified 2026-08-26)
    return Response(r.status_code, dict(r.headers), r.text)


async def _curl_cffi_request(method: str, url: str, *, headers, params,
                             timeout: float) -> Response:
    from curl_cffi.requests import AsyncSession
    async with AsyncSession(impersonate="chrome") as session:
        r = await session.request(method, url, headers=headers, params=params,
                                  timeout=timeout)
        return Response(r.status_code, dict(r.headers), r.text)


async def get_json(url: str, *, source: str | None = None,
                   headers: dict[str, str] | None = None,
                   params: dict[str, Any] | None = None,
                   timeout: float = 20.0) -> Any:
    r = await request("GET", url, source=source, headers=headers,
                      params=params, timeout=timeout)
    try:
        r.raise_for_status()
        return r.json()
    except HTTPStatusError:
        raise
    except Exception as exc:
        raise _wrap(exc) from exc


async def get_text(url: str, *, source: str | None = None,
                   headers: dict[str, str] | None = None,
                   params: dict[str, Any] | None = None,
                   timeout: float = 20.0) -> str:
    """Floor-checked raw-text GET (XML/HTML endpoints — arxiv, feeds)."""
    r = await request("GET", url, source=source, headers=headers,
                      params=params, timeout=timeout)
    try:
        r.raise_for_status()
        return r.text
    except HTTPStatusError:
        raise
    except Exception as exc:
        raise _wrap(exc) from exc
