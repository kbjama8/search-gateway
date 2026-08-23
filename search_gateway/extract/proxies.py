"""Proxy subsystem — env-gated, provider-agnostic, sticky-per-profile.

Disabled by default (zero-cost doctrine). When enabled, every browser
profile gets one pinned residential egress for its session lifetime
(sticky), and the fingerprint bundle is aligned to the egress geo — the
network family drives the locale family (LESSONS.md §1.2, §2.2).

Credentials come from SEARCH_GATEWAY_PROXY_* or `~/.agent-reach/proxy.env`
(0600). The username carries the provider's targeting grammar; when unset we
build the industry-standard `country-sid-ttl` form (LESSONS.md §2.2).
"""

from __future__ import annotations

import hashlib
import logging

import redis

from ..config import (
    PROXY_COUNTRY,
    PROXY_ENABLED,
    PROXY_ENV_FILE,
    PROXY_GATEWAY,
    PROXY_GEO_ALIGN,
    PROXY_PASSWORD,
    PROXY_PROTOCOL,
    PROXY_STICKY_TTL,
    PROXY_USERNAME,
    REDIS_URL,
    load_env_file,
)
from .fingerprints import GEO_LOCALE, derive_for_geo, lint

logger = logging.getLogger("search_gateway.extract.proxies")

_client: redis.Redis | None = None


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _client


def enabled() -> bool:
    return bool(PROXY_ENABLED and PROXY_GATEWAY)


def _credentials() -> tuple[str, str]:
    username = PROXY_USERNAME
    password = PROXY_PASSWORD
    if not username:
        loaded = load_env_file(PROXY_ENV_FILE,
                               {"SEARCH_GATEWAY_PROXY_USERNAME",
                                "SEARCH_GATEWAY_PROXY_PASSWORD"})
        username = loaded.get("SEARCH_GATEWAY_PROXY_USERNAME", "")
        password = loaded.get("SEARCH_GATEWAY_PROXY_PASSWORD", password)
    return username, password


def sticky_session_id(profile: str) -> str:
    """Stable per-profile sticky id — the same profile keeps the same egress
    within a TTL window (renews per provision)."""
    return hashlib.sha256(f"sg-profile:{profile}".encode()).hexdigest()[:16]


def _build_username(profile: str) -> str:
    """Provider grammar: country-sid-<sticky>-ttl-<ttl> (ProxyHat-style,
    LESSONS.md §2.2). A verbatim PROXY_USERNAME always wins."""
    base, _ = _credentials()
    if base:
        return base
    parts = [PROXY_COUNTRY or "any", f"sid-{sticky_session_id(profile)}",
             f"ttl-{PROXY_STICKY_TTL}"]
    return "-".join(parts)


def context_proxy(profile: str) -> dict[str, str] | None:
    """Playwright/Camoufox-style proxy dict for a profile (None if disabled)."""
    if not enabled():
        return None
    _, password = _credentials()
    return {
        "server": f"{PROXY_PROTOCOL}://{PROXY_GATEWAY}",
        "username": _build_username(profile),
        "password": password,
    }


def jina_header() -> str | None:
    """X-Proxy-Url value for Jina Reader (same sticky grammar, URL-encoded
    userinfo)."""
    proxy = context_proxy("readurl")
    if proxy is None:
        return None
    return (f"{PROXY_PROTOCOL}://{proxy['username']}:{proxy['password']}"
            f"@{PROXY_GATEWAY}")


def country() -> str:
    return PROXY_COUNTRY.upper()


def align_bundle(bundle: dict, country_code: str | None = None) -> dict:
    """Align a fingerprint bundle to the egress country (network → locale).
    No-op when disabled, no country known, or the country is unmapped —
    guessing a locale is worse than leaving the operator's bundle alone."""
    cc = (country_code or country()).upper()
    if not (enabled() and PROXY_GEO_ALIGN and cc in GEO_LOCALE):
        return bundle
    aligned = dict(bundle)
    aligned.update(derive_for_geo(cc))
    problems = lint(aligned)
    if problems:
        logger.warning("proxy-aligned bundle still incoherent: %s", problems)
    return aligned


def record_success(profile: str) -> None:
    _record(profile, ok=True)


def record_failure(profile: str) -> None:
    _record(profile, ok=False)


def _record(profile: str, *, ok: bool) -> None:
    if not enabled():
        return
    try:
        c = _get_client()
        sid = sticky_session_id(profile)
        pipe = c.pipeline()
        pipe.incr(f"sg:px:{sid}:total")
        if not ok:
            pipe.incr(f"sg:px:{sid}:err")
        pipe.expire(f"sg:px:{sid}:total", 86400)
        pipe.expire(f"sg:px:{sid}:err", 86400)
        pipe.execute()
    except redis.RedisError as exc:
        logger.debug("proxy health write error: %s", exc)


def health(profile: str) -> dict:
    try:
        c = _get_client()
        sid = sticky_session_id(profile)
        total = int(c.get(f"sg:px:{sid}:total") or 0)
        err = int(c.get(f"sg:px:{sid}:err") or 0)
        return {"total": total, "errors": err,
                "reliability": round(1.0 - err / total, 3) if total else 1.0}
    except redis.RedisError as exc:
        logger.debug("proxy health read error: %s", exc)
        return {"total": 0, "errors": 0, "reliability": 1.0}
