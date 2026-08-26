"""DR-1 challenge fixture vault — real recorded challenge pages drive the
detector regression suite.

Provenance (all captured 2026-08-25 with a research-style curl UA):
  cloudflare_crunchbase  — CF managed challenge page (HTTP 200, challenge-platform)
  cloudflare_indeed      — CF challenge page (HTTP 403, challenge-platform)
  datadome_g2            — DataDome wall (x-datadome: protected + datadome
                           cookie + __cf_bm) on a site behind BOTH vendors

The fixture HTML is static and machine-local; it never re-fetches at test
time. Headers files carry the raw captured response headers (one per line).
"""

from __future__ import annotations

from pathlib import Path

from kortex_search.extract.detectors import classify

_FIXTURES = Path(__file__).parent / "fixtures" / "challenges"


def _load(name: str) -> tuple[int, dict[str, str], str]:
    headers: dict[str, str] = {}
    hdr_path = _FIXTURES / f"{name}.headers.txt"
    if hdr_path.exists():
        for line in hdr_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and ":" in line and not line.lower().startswith("http/"):
                k, _, v = line.partition(":")
                headers[k.strip().lower()] = v.strip()
    body = (_FIXTURES / f"{name}.html").read_text(encoding="utf-8")
    return 200, headers, body


class TestRealChallengeFixtures:
    def test_cloudflare_crunchbase(self):
        status, headers, body = _load("cloudflare_crunchbase")
        sig = classify(status, headers, body)
        assert sig is not None
        assert sig.vendor == "cloudflare"
        assert sig.level == "transient"
        assert "challenge-platform" in body  # the recorded marker

    def test_cloudflare_indeed(self):
        status, headers, body = _load("cloudflare_indeed")
        sig = classify(status, headers, body)
        assert sig is not None
        assert sig.vendor == "cloudflare"
        assert "challenge-platform" in body

    def test_datadome_g2_specific_wall_wins_over_cf_cookie(self):
        # g2 sets BOTH __cf_bm and datadome cookies + x-datadome: protected —
        # the DataDome wall is the actionable signal and must win
        status, headers, body = _load("datadome_g2")
        assert "__cf_bm" in headers.get("set-cookie", "")
        sig = classify(status, headers, body)
        assert sig is not None
        assert sig.vendor == "datadome"
        assert sig.level == "ip"


class TestExtendedMarkers:
    def test_datadome_x_header(self):
        sig = classify(403, {"x-datadome": "protected"}, "")
        assert sig.vendor == "datadome" and sig.level == "ip"

    def test_cloudflare_challenge_platform_body(self):
        sig = classify(200, {}, "challenge-platform/scripts/jsd/main.js")
        assert sig.vendor == "cloudflare"

    def test_kasada_body_marker(self):
        sig = classify(403, {}, "var kpsdk = { ... }")
        assert sig.vendor == "kasada"

    def test_akamai_abck_cookie(self):
        sig = classify(403, {"set-cookie": "_abck=abc; Path=/"}, "")
        assert sig.vendor == "akamai"

    def test_perimeterx_px3_cookie(self):
        sig = classify(403, {"set-cookie": "_px3=abc"}, "")
        assert sig.vendor == "perimeterx"

    def test_arkose_funcaptcha_body(self):
        sig = classify(403, {}, "funcaptcha.com/api/fc/gfct/")
        assert sig.vendor == "arkose"
