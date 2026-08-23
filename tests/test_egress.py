"""L1 egress floor tests — pure IP/hostname checks, no network, no DNS."""

from __future__ import annotations

import pytest

from search_gateway.extract import egress


class TestFloorPure:
    @pytest.mark.parametrize("url", [
        "http://169.254.169.254/latest/meta-data",        # AWS IMDS
        "https://169.254.169.254/latest/meta-data/iam/",  # IAM creds surface
        "http://metadata.google.internal/computeMetadata/v1/",  # GCP
        "http://metadata/",                               # bare metadata name
        "http://metadata.azure.internal/",                # Azure
        "http://169.254.170.2/",                          # ECS metadata
        "http://169.254.170.23/",                         # ECS task role
        "http://100.100.100.200/latest/meta-data",        # Alibaba IMDS
        "http://10.0.0.1/", "http://10.255.255.255/",     # RFC1918 A
        "http://172.16.0.1/", "http://172.31.255.254/",   # RFC1918 B
        "http://192.168.1.1/", "http://192.168.255.254/", # RFC1918 C
        "http://127.0.0.2/", "http://127.255.255.254/",   # loopback (other hosts)
        "https://[::1]/",
        "https://[fe80::1]/",
        "https://[fd00:ec2::254]/",                       # Azure IMDS v6
        "http://localhost/",
        "http://foo.localhost/",
        "http://router.local/",
        "http://0.0.0.0/",
        "https://[::]/",
        "http://100.64.0.1/", "http://100.127.255.254/",  # CGNAT
    ])
    def test_imds_and_private_blocked(self, url):
        blocked, reason = egress.is_always_blocked_url(url)
        assert blocked, url
        assert reason

    @pytest.mark.parametrize("url", [
        "https://example.com/",
        "https://www.google.com/search?q=x",
        "https://api.deepseek.com/chat/completions",
        "https://r.jina.ai/",
        "http://10.invalid.example/",   # NOT 10.0.0.0/8 — no DNS in the floor
        "https://example.com:8443/",
        "ftp://example.com/file",       # non-http schemes parse the same
        "not a url",
        "",
    ])
    def test_public_allowed(self, url):
        blocked, _reason = egress.is_always_blocked_url(url)
        assert not blocked, url

    def test_case_and_dot_insensitivity(self):
        assert egress.is_always_blocked_url("http://METADATA.GOOGLE.INTERNAL./")[0]
        assert egress.is_always_blocked_url("http://Localhost/")[0]
        assert egress.is_always_blocked_url("HTTP://169.254.169.254/")[0]

    def test_userinfo_host_parsing(self):
        # the host is what's checked, not userinfo or path
        assert egress.is_always_blocked_url("http://169.254.169.254/")[0]
        # a non-literal hostname is never resolved by the floor (no DNS in the
        # floor) — it passes here, and the L3 kernel filter catches what the
        # floor can't see
        assert not egress.is_always_blocked_url(
            "http://169.254.169.254.evil.com/")[0]


class TestExemptions:
    def test_searxng_exempt(self, monkeypatch):
        monkeypatch.setattr(egress, "SEARXNG_BASE", "http://127.0.0.1:8888")
        monkeypatch.setattr(egress, "REDIS_URL", "redis://127.0.0.1:6379/0")
        monkeypatch.setattr(egress, "FLOOR_EXEMPT", "")
        blocked, _ = egress.is_always_blocked_url("http://127.0.0.1:8888/search")
        assert not blocked
        blocked, _ = egress.is_always_blocked_url("http://127.0.0.1:6379/0")
        assert not blocked
        # other loopback hosts stay blocked
        blocked, _ = egress.is_always_blocked_url("http://127.0.0.2/")
        assert blocked

    def test_exempt_list_override(self, monkeypatch):
        monkeypatch.setattr(egress, "SEARXNG_BASE", "http://127.0.0.1:8888")
        monkeypatch.setattr(egress, "REDIS_URL", "redis://127.0.0.1:6379/0")
        monkeypatch.setattr(egress, "FLOOR_EXEMPT", "10.20.30.40, internal.example")
        assert not egress.is_always_blocked_url("http://10.20.30.40/")[0]
        assert not egress.is_always_blocked_url("http://internal.example/")[0]
        # the allowlist only exempts exactly those hosts
        assert egress.is_always_blocked_url("http://10.20.30.41/")[0]

    def test_floor_flag_off_passes_everything(self, monkeypatch):
        monkeypatch.setattr(egress, "EGRESS_FLOOR", False)
        blocked, _ = egress.check_egress("http://169.254.169.254/")
        assert not blocked


class TestCheckAndRaise:
    def test_check_egress_records_telemetry(self, monkeypatch, rds):
        monkeypatch.setattr(egress, "EGRESS_FLOOR", True)
        monkeypatch.setattr(egress, "FLOOR_EXEMPT", "")
        blocked, reason = egress.check_egress("http://169.254.169.254/", "web")
        assert blocked and reason
        bl = egress.blocks_snapshot()
        assert bl["counters"].get("web:floor", 0) == 1
        assert bl["recent"][-1]["source"] == "web"

    def test_assert_egress_raises(self, monkeypatch, rds):
        monkeypatch.setattr(egress, "EGRESS_FLOOR", True)
        with pytest.raises(egress.EgressBlocked) as excinfo:
            egress.assert_egress("http://169.254.169.254/latest/meta-data")
        assert "egress-floor" in str(excinfo.value)

    def test_assert_egress_allows_public(self, monkeypatch):
        monkeypatch.setattr(egress, "EGRESS_FLOOR", True)
        egress.assert_egress("https://example.com/article/1")  # no raise


class TestStatusSection:
    def test_status_shape(self, monkeypatch, rds):
        monkeypatch.setattr(egress, "EGRESS_FLOOR", True)
        st = egress.status()
        assert st["floor"]["enabled"] is True
        assert set(st) == {"floor", "proxy", "kernel", "denied_count",
                           "last_denial"}
        assert st["proxy"]["enabled"] is False
        assert st["kernel"]["installed"] is None


class TestHooks:
    pytestmark = pytest.mark.asyncio
    async def test_http_request_denied(self, monkeypatch, rds):
        from search_gateway.extract.http import get_json, request
        monkeypatch.setattr(egress, "EGRESS_FLOOR", True)
        with pytest.raises(egress.EgressBlocked):
            await request("GET", "http://169.254.169.254/", source="bilibili")
        with pytest.raises(egress.EgressBlocked):
            await get_json("http://192.168.1.1/status")

    async def test_web_read_denied(self, monkeypatch, rds):
        from search_gateway.sources.web import WebSource
        monkeypatch.setattr(egress, "EGRESS_FLOOR", True)
        with pytest.raises(egress.EgressBlocked):
            await WebSource().read("http://169.254.169.254/latest/meta-data")

    async def test_camoufox_html_denied(self, monkeypatch, rds):
        from search_gateway.extract import camoufox
        monkeypatch.setattr(egress, "EGRESS_FLOOR", True)
        assert await camoufox.html(None, "http://169.254.169.254/") is None

    async def test_server_read_url_names_egress(self, monkeypatch, rds):
        from search_gateway import server
        monkeypatch.setattr(egress, "EGRESS_FLOOR", True)
        out = await server.read_url("http://169.254.169.254/latest/meta-data")
        assert "egress-floor" in out["error"]
