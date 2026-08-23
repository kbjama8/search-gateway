"""Camoufox anonymous-tier adapter (experimental, lazy).

Camoufox (Firefox ESR + browserforge fingerprints) is the 2026 leader for
anonymous extraction against DataDome-class control planes (LESSONS.md §1.1).
This module is the thin seam: gated by SEARCH_GATEWAY_STEALTH, lazily
imported, and every failure degrades to (None, reason) — the caller's
fallback chain decides what happens next.

The authenticated OpenCLI tier is untouched; this is the *anonymous* path
for new/CN sources (PLAN.md Phase 3, dual-path decision D2).
"""

from __future__ import annotations

import logging

from ..config import STEALTH_ENABLED, STEALTH_PROFILE
from .proxies import context_proxy

logger = logging.getLogger("search_gateway.extract.camoufox")


def available() -> tuple[bool, str]:
    """Is the stealth tier usable right now?"""
    if not STEALTH_ENABLED:
        return False, "disabled (SEARCH_GATEWAY_STEALTH=0)"
    try:
        import camoufox  # noqa: F401
    except ImportError:
        return False, "camoufox package not installed"
    return True, "ok"


async def launch(profile: str, *, headless: str = "virtual"):
    """Launch a Camoufox browser bound to the profile's proxy + fingerprint.

    Returns (browser, reason); browser is None on any failure — never raise.
    """
    ok, reason = available()
    if not ok:
        return None, reason
    try:
        from camoufox import AsyncCamoufox
    except ImportError:
        return None, "camoufox package not installed"

    kwargs: dict = {"headless": headless}
    if STEALTH_PROFILE:
        kwargs["fingerprint_preset"] = STEALTH_PROFILE
    proxy = context_proxy(profile)
    if proxy:
        kwargs["proxy"] = proxy

    try:
        browser = AsyncCamoufox(**kwargs)
        await browser.start()
        logger.info("camoufox started (profile=%s, preset=%s)",
                    profile, STEALTH_PROFILE or "browserforge")
        return browser, ""
    except Exception as exc:  # noqa: BLE001 — degrade, never raise
        logger.warning("camoufox launch failed: %s", exc)
        return None, f"{type(exc).__name__}: {exc}"


async def html(browser, url: str, *, timeout_ms: int = 30000) -> str | None:
    """Fetch rendered HTML from an already-launched browser. None on failure."""
    if browser is None:
        return None
    try:
        page = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded",
                        timeout=timeout_ms)
        return await page.content()
    except Exception as exc:  # noqa: BLE001
        logger.debug("camoufox html fetch failed: %s", exc)
        return None
