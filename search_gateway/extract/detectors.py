"""Block & challenge intelligence.

Turns a response (status + headers + body) into a classified `BlockSignal`:
which vendor is challenging us, at what level, on what evidence. The action
ladder consumes the signal; this module only observes.

Doctrine: captcha → `skip` + flag. We never solve; we detect, back off, and
name the state in the envelope. The only vendor-published signal is
Cloudflare's `cf-mitigated: challenge` header (see LESSONS.md §1.4); the rest
are heuristic markers, fixture-tested so they rot loudly.
"""

from __future__ import annotations

from dataclasses import dataclass

_CF_BODY_MARKERS = ("just a moment", "cf-chl", "cf_chl", "turnstile",
                    "checking your browser", "challenge-platform")
_CN_MARKERS = {
    "bilibili": ("v_voucher", "风控校验", "访问异常"),
    "xhs": ("操作过于频繁", "请求过于频繁", "请稍后再试"),
    "zhihu": ("人机验证", "请完成验证", "环境异常"),
    "weibo": ("访问频率过快",
              "系统检测到您的网络环境"),
}


@dataclass(frozen=True)
class BlockSignal:
    """A detected challenge. `level` drives which ladder rung we take."""

    vendor: str      # cloudflare | datadome | perimeterx | kasada | akamai
                     # | arkose | bilibili | xhs | zhihu | weibo | youtube | generic
    level: str       # transient (challenge page) | ip (rate/ban on
                     # address) | account (session flagged)
    evidence: str


def classify(status: int, headers: dict[str, str] | None,
             body: str | None) -> BlockSignal | None:
    """Classify a response; None when no challenge is detected."""
    hdrs = {k.lower(): v for k, v in (headers or {}).items()}
    # scan the FULL body — challenge markers land anywhere (DR-1 fixture:
    # cloudflare_crunchbase carries challenge-platform at char ~127k);
    # substring scans are linear and cheap
    text = body or ""
    low = text.lower()

    # Official Cloudflare signal (verified primary doc, LESSONS.md §1.4).
    if hdrs.get("cf-mitigated") == "challenge":
        return BlockSignal("cloudflare", "transient", "cf-mitigated: challenge")

    # Vendor-specific walls first — a page can carry CF cookies AND a
    # DataDome/PerimeterX wall (verified live: g2.com sets __cf_bm + datadome);
    # the specific wall is the actionable signal, so it wins over the CF
    # cookie heuristic below (DR-1, 2026-08-25).
    if (hdrs.get("x-datadome", "") == "protected"
            or "datadome" in (hdrs.get("set-cookie", "") + " " + low)):
        return BlockSignal("datadome", "ip", "datadome marker")

    if "_pxcaptcha" in low or "_px" in hdrs.get("set-cookie", "") \
            or "_px3" in hdrs.get("set-cookie", "") or "perimeterx" in low:
        return BlockSignal("perimeterx", "transient", "perimeterx marker")

    if any(k.startswith("x-kpsdk") for k in hdrs) or "kpsdk" in low:
        return BlockSignal("kasada", "transient", "x-kpsdk marker")

    if "ak_bmsc" in (hdrs.get("set-cookie", "") or "") \
            or "_abck" in (hdrs.get("set-cookie", "") or ""):
        return BlockSignal("akamai", "transient", "akamai bot-manager cookie")

    if "arkoselabs" in low or "funcaptcha" in low or "arkose" in low \
            or "x-algolia" in hdrs.get("set-cookie", ""):
        return BlockSignal("arkose", "transient", "arkose marker")

    # Cloudflare cookie/body heuristics (after the specific walls above).
    if "__cf_bm" in (hdrs.get("set-cookie", "") or "") or any(
            m in low for m in _CF_BODY_MARKERS):
        return BlockSignal("cloudflare", "transient",
                           "cf challenge marker (cookie/body)")

    for vendor, markers in _CN_MARKERS.items():
        if any(m in text for m in markers):
            return BlockSignal(vendor, "ip", f"{vendor} risk-control marker")

    if "sign in to confirm you're not a bot" in low:
        return BlockSignal("youtube", "ip", "yt bot-check wall")

    if status == 429:
        return BlockSignal("generic", "ip", "http 429")
    if status == 403 and "captcha" in low:
        return BlockSignal("generic", "transient", "403 captcha")

    return None


def ladder_action(signal: BlockSignal | None, *, attempts: int,
                  profile_quarantined: bool = False) -> str:
    """Map a signal to the next ladder rung.

    Rungs: retry → throttle → rotate_profile → rotate_ip → quarantine → skip.
    """
    if signal is None:
        return "none"
    if signal.level == "transient" and attempts < 1:
        return "retry"
    if signal.level == "ip":
        return "rotate_ip" if attempts >= 1 else "throttle"
    if signal.level == "account":
        return "quarantine" if profile_quarantined else "rotate_profile"
    return "skip"
