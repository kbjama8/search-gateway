"""Bilibili source — B站 search API with wbi signing.

Since March 2023 Bilibili's web APIs require a wbi signature (`w_rid` +
`wts`); unsigned or mis-signed requests return a `v_voucher` risk-control
payload instead of results (LESSONS.md §3.4). Algorithm:

  1. `img_key` + `sub_key` come from the nav API's `wbi_img` URLs (the URLs
     are disguised tokens — only the filename stems matter). Keys rotate
     daily, so they are cached (Redis, 23h TTL; in-memory fallback).
  2. `mixin_key` = first 32 chars of (img_key + sub_key) reordered through
     the 64-entry MIXIN_KEY_ENC_TAB.
  3. `w_rid` = MD5( urlencoded(params + wts) sorted by key + mixin_key ),
     with encodeURIComponent semantics (uppercase hex, spaces as %20).

The signing helpers are pure and fixture-tested against the canonical
worked example (mixin `ea1db124af3c7062474693fa704f4ff8`).
"""

from __future__ import annotations

import hashlib
import logging
import time
import urllib.parse

import redis

from ..config import BILIBILI_WBI, BILIBILI_WBI_KEY_TTL, REDIS_URL
from ..extract.http import get_json
from ..models import Result
from .base import Source, SourceError

logger = logging.getLogger("kortex_search.sources.bilibili")

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]

_NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
_SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/all/v2"
_REDIS_IMG, _REDIS_SUB = "ks:bili:wbi:img", "ks:bili:wbi:sub"

_client: redis.Redis | None = None
# in-memory fallback when Redis is unreachable (fresh fetch on expiry)
_mem_cache: dict[str, str | float] = {"img": "", "sub": "", "at": 0.0}


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _client


def _encode(value) -> str:
    """encodeURIComponent semantics: uppercase percent-hex, %20 for spaces,
    `!'()*` left unencoded."""
    return urllib.parse.quote(str(value), safe="!~*'()")


def mixin_key(img_key: str, sub_key: str) -> str:
    """Reorder img_key+sub_key through MIXIN_KEY_ENC_TAB; first 32 chars."""
    raw = img_key + sub_key
    return "".join(raw[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def sign_params(params: dict, img_key: str, sub_key: str,
                wts: int | None = None) -> dict:
    """Return `params` extended with a valid `w_rid` + `wts` (pure function).

    `params` values may be non-string (ints/bools); they are encoded the way
    encodeURIComponent would. The original params order is preserved — only
    the signed copy is sorted (per the canonical spec).
    """
    wts = int(wts or time.time())
    signed = {k: _encode(v) for k, v in params.items()}
    signed["wts"] = str(wts)
    query = "&".join(f"{k}={signed[k]}" for k in sorted(signed))
    # MD5 is mandated by Bilibili's wbi spec (LESSONS.md §3.4) — this is
    # a signature format, not a cryptographic use.
    digest = hashlib.md5(  # noqa: S324
        (query + mixin_key(img_key, sub_key)).encode()).hexdigest()
    out = dict(params)
    out["w_rid"] = digest
    out["wts"] = wts
    return out


def _stem(url: str) -> str:
    return (url or "").rsplit("/", 1)[-1].replace(".png", "")


async def _fetch_keys() -> tuple[str, str]:
    """Nav API → (img_key, sub_key). Returns empty strings on failure so the
    caller degrades to an unsigned request rather than crashing."""
    try:
        data = await get_json(_NAV_URL, source="bilibili",
                              headers={"User-Agent": "Mozilla/5.0 (X11; Linux "
                                      "x86_64) AppleWebKit/537.36",
                                       "Referer": "https://www.bilibili.com"},
                              timeout=10.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("bilibili nav key fetch failed: %s", exc)
        return "", ""
    wbi = ((data or {}).get("data") or {}).get("wbi_img") or {}
    return _stem(wbi.get("img_url") or ""), _stem(wbi.get("sub_url") or "")


async def wbi_keys() -> tuple[str, str]:
    """Cached wbi keys (Redis with TTL, in-memory fallback)."""
    img, sub = "", ""
    try:
        c = _get_client()
        img, sub = c.get(_REDIS_IMG) or "", c.get(_REDIS_SUB) or ""
    except redis.RedisError:
        pass
    if (not (img and sub)
            and time.time() - float(_mem_cache["at"]) < BILIBILI_WBI_KEY_TTL):
        img, sub = str(_mem_cache["img"]), str(_mem_cache["sub"])
    if not (img and sub):
        img, sub = await _fetch_keys()
        if img and sub:
            _mem_cache.update(img=img, sub=sub, at=time.time())
            try:
                c = _get_client()
                c.set(_REDIS_IMG, img, ex=BILIBILI_WBI_KEY_TTL)
                c.set(_REDIS_SUB, sub, ex=BILIBILI_WBI_KEY_TTL)
            except redis.RedisError:
                pass
    return img, sub


class BilibiliSource(Source):
    name = "bilibili"
    description = "Bilibili search (B站 API, wbi-signed)."
    source_type = "video"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        params: dict = {"keyword": query}
        if BILIBILI_WBI:
            img, sub = await wbi_keys()
            if img and sub:
                params = sign_params(params, img, sub)
            else:
                logger.warning("bilibili wbi keys unavailable — unsigned request")
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com",
        }
        try:
            payload = await get_json(_SEARCH_URL, source="bilibili",
                                     params=params, headers=headers)
        except Exception as exc:
            raise SourceError(f"bilibili request failed: {exc}") from exc

        code = payload.get("code")
        if code != 0:
            raise SourceError(f"bilibili API code {code}: "
                              f"{payload.get('message', '')}")

        results: list[Result] = []
        for block in payload.get("data", {}).get("result", []):
            rtype = block.get("result_type", "")
            items = block.get("data") or []
            if not isinstance(items, list):
                continue
            for it in items:
                if not isinstance(it, dict):
                    continue
                title = (it.get("title") or "").replace(
                    '<em class="keyword">', "").replace("</em>", "")
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
            img, sub = await wbi_keys()
            if not (img and sub):
                return False, "wbi keys unavailable"
            params = sign_params({"keyword": "test"}, img, sub)
            payload = await get_json(_SEARCH_URL, source="bilibili",
                                     params=params,
                                     headers={"User-Agent": "Mozilla/5.0"})
            return payload.get("code") == 0, f"code {payload.get('code')}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)
