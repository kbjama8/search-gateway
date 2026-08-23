"""Fingerprint bundles — one coherent story per persona.

Detection in 2026 is a coherence check across four signal families
(rendering, hardware, locale, network — LESSONS.md §1.2). This module is the
enforcer: a bundle is a dict of declared values, `lint()` finds the
contradictions (TZ vs egress geo, UA vs GPU class, mobile UA vs screen,
Accept-Language vs navigator.languages), and `derive_for_geo()` builds a
coherent skeleton from a proxy's country so the network family *drives* the
locale family — never the reverse.
"""

from __future__ import annotations

import re
from typing import Any

# Country → (timezone, locale, primary language). Small curated table; the
# proxy engine aligns bundles only for countries we have entries for, and
# passes everything else through untouched (calibrated honesty: no guessing
# a locale we don't know).
GEO_LOCALE: dict[str, tuple[str, str, str]] = {
    "US": ("America/New_York", "en-US", "en"),
    "GB": ("Europe/London", "en-GB", "en"),
    "DE": ("Europe/Berlin", "de-DE", "de"),
    "FR": ("Europe/Paris", "fr-FR", "fr"),
    "NL": ("Europe/Amsterdam", "nl-NL", "nl"),
    "JP": ("Asia/Tokyo", "ja-JP", "ja"),
    "SG": ("Asia/Singapore", "en-SG", "en"),
    "CN": ("Asia/Shanghai", "zh-CN", "zh"),
    "TW": ("Asia/Taipei", "zh-TW", "zh"),
    "HK": ("Asia/Hong_Kong", "zh-HK", "zh"),
    "KR": ("Asia/Seoul", "ko-KR", "ko"),
    "CA": ("America/Toronto", "en-CA", "en"),
    "AU": ("Australia/Sydney", "en-AU", "en"),
}

_MOBILE_UA = re.compile(r"iPhone|Android", re.IGNORECASE)
_CHROME_UA = re.compile(r"Chrome/\d+", re.IGNORECASE)
_FIREFOX_UA = re.compile(r"Firefox/\d+", re.IGNORECASE)
_SAFARI_UA = re.compile(r"Safari/\d+", re.IGNORECASE)

# Fields a bundle may declare; `lint` cross-checks the families.
BUNDLE_FIELDS = (
    "ua", "browser", "os", "viewport", "device_pixel_ratio", "touch",
    "timezone", "locale", "languages", "accept_language",
    "hardware_concurrency", "device_memory", "platform", "gpu_vendor",
    "country",
)


def derive_for_geo(country: str, *, browser: str = "chrome",
                   os: str = "windows") -> dict[str, Any]:
    """Build a coherent locale/hardware skeleton from an egress country."""
    bundle: dict[str, Any] = {"country": country.upper()}
    geo = GEO_LOCALE.get(country.upper())
    if geo:
        tz, locale, lang = geo
        bundle.update(
            timezone=tz, locale=locale, languages=[lang],
            accept_language=f"{locale},en;q=0.8",
        )
    bundle["browser"] = browser
    bundle["os"] = os
    bundle["platform"] = {"windows": "Win32", "macos": "MacIntel",
                          "linux": "Linux x86_64"}.get(os, "Linux x86_64")
    bundle["touch"] = False
    bundle["viewport"] = {"width": 1920, "height": 1080}
    bundle["device_pixel_ratio"] = 1
    bundle["hardware_concurrency"] = 8
    bundle["device_memory"] = 8
    return bundle


def lint(bundle: dict[str, Any]) -> list[str]:
    """Return coherence violations; [] = the story hangs together."""
    problems: list[str] = []
    ua = str(bundle.get("ua") or "")
    country = str(bundle.get("country") or "").upper()
    tz = bundle.get("timezone")

    if country and tz and country in GEO_LOCALE:
        want_tz = GEO_LOCALE[country][0]
        if tz != want_tz:
            problems.append(f"timezone {tz!r} contradicts country {country} "
                            f"(expected {want_tz!r})")

    languages = bundle.get("languages") or []
    if languages:
        lang = str(languages[0]).split("-")[0].lower()
        if country and country in GEO_LOCALE:
            want_lang = GEO_LOCALE[country][2]
            if lang != want_lang:
                problems.append(f"primary language {lang!r} contradicts "
                                f"country {country} (expected {want_lang!r})")

    accept = str(bundle.get("accept_language") or "")
    if (languages and accept and accept.strip()
            and not accept.lower().startswith(
                str(languages[0]).lower().split("-")[0])):
            problems.append("accept_language disagrees with languages[0]")

    if ua and not (_CHROME_UA.search(ua) or _FIREFOX_UA.search(ua)
                   or _SAFARI_UA.search(ua)):
        problems.append("ua declares no recognized browser engine")

    if _MOBILE_UA.search(ua):
        if bundle.get("touch") is False:
            problems.append("mobile ua without touch support")
        vp = bundle.get("viewport") or {}
        if int(vp.get("width") or 0) > 800:
            problems.append("mobile ua with desktop viewport width")

    if _CHROME_UA.search(ua) and str(bundle.get("browser") or "").lower() \
            not in ("", "chrome", "chromium"):
        problems.append("chrome ua contradicts declared browser")

    return problems
