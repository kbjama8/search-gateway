"""Extraction layer tests (Project Gatekeeper) — hermetic, no live deps."""

from __future__ import annotations

import pytest

from kortex_search.extract import (
    canonicalize_results,
    detectors,
    fingerprints,
    router,
    scheduler,
)
from kortex_search.extract import parse as ext_parse
from kortex_search.extract import profiles as profiles_mod
from kortex_search.extract import proxies as proxies_mod

# --- parse.py -----------------------------------------------------------

class TestCanonicalize:
    def test_alias_mapping_and_meta(self):
        items = [{"title": "T", "url": "u", "content": "snippet text",
                  "published": "2026-01-02", "stars": 42}]
        out = canonicalize_results(items, source="github", engine="github-api",
                                   source_type="repo")
        assert len(out) == 1
        r = out[0]
        assert r.title == "T"
        assert r.url == "u"
        assert r.snippet == "snippet text"
        assert r.published == "2026-01-02"
        assert r.meta["stars"] == 42
        assert r.meta["source_type"] == "repo"

    def test_drops_uncitable(self):
        out = canonicalize_results([{"stars": 1}, "not-a-dict"], source="x")
        assert out == []

    def test_alias_fallbacks(self):
        items = [{"name": "A", "link": "https://a", "description": "d"}]
        out = canonicalize_results(items, source="x")
        assert out[0].title == "A"
        assert out[0].url == "https://a"
        assert out[0].snippet == "d"


class TestParseJsonld:
    def test_extracts_objects(self):
        html = ('<html><script type="application/ld+json">'
                '{"@type": "NewsArticle", "headline": "H"}</script></html>')
        blocks = ext_parse.parse_jsonld(html)
        assert blocks == [{"@type": "NewsArticle", "headline": "H"}]

    def test_skips_malformed(self):
        html = ('<script type="application/ld+json">{broken</script>'
                '<script type="application/ld+json">{"ok": 1}</script>')
        assert ext_parse.parse_jsonld(html) == [{"ok": 1}]

    def test_handles_lists(self):
        html = '<script type="application/ld+json">[{"a": 1}, {"b": 2}]</script>'
        assert ext_parse.parse_jsonld(html) == [{"a": 1}, {"b": 2}]


class TestParseCss:
    def test_parallel_columns(self):
        html = ('<div class="r"><a class="t" href="/1">One</a>'
                '<p class="s">snippet one</p></div>'
                '<div class="r"><a class="t" href="/2">Two</a>'
                '<p class="s">snippet two</p></div>')
        rows = ext_parse.parse_css(html, [
            ("a.t", "title", ""), ("a.t", "url", "href"),
            ("p.s", "snippet", ""),
        ])
        assert rows == [
            {"title": "One", "url": "/1", "snippet": "snippet one"},
            {"title": "Two", "url": "/2", "snippet": "snippet two"},
        ]


class TestParseRegex:
    def test_row_zip(self):
        text = "A: apple\nB: banana\nA: apricot"
        rows = ext_parse.parse_regex(text, [
            (r"^A: (.+)$", "a", "1"), (r"^B: (.+)$", "b", "1")])
        assert rows == [{"a": "apple", "b": "banana"}, {"a": "apricot"}]


class TestParseShapes:
    @pytest.mark.asyncio
    async def test_json_path_ladder(self):
        text = '{"payload": {"hits": [{"title": "T", "url": "u"}]}}'
        out = await ext_parse.parse_shapes(
            text, source="s", json_path=lambda d: d["payload"]["hits"])
        assert len(out) == 1 and out[0].title == "T"

    @pytest.mark.asyncio
    async def test_no_shapes_no_llm(self, monkeypatch):
        monkeypatch.setattr(ext_parse, "LLM_PARSE", False)
        out = await ext_parse.parse_shapes("plain text", source="s")
        assert out == []


# --- detectors.py -------------------------------------------------------

class TestDetectors:
    def test_cloudflare_official_header(self):
        sig = detectors.classify(200, {"cf-mitigated": "challenge"}, "")
        assert sig is not None
        assert sig.vendor == "cloudflare" and sig.level == "transient"

    def test_cloudflare_cookie(self):
        sig = detectors.classify(200, {"set-cookie": "__cf_bm=abc"}, "")
        assert sig is not None and sig.vendor == "cloudflare"

    def test_cloudflare_body(self):
        sig = classifiers_helper(200, {}, "Just a moment...")
        assert sig.vendor == "cloudflare"

    def test_datadome(self):
        sig = detectors.classify(403, {"set-cookie": "datadome=1"}, "")
        assert sig.vendor == "datadome" and sig.level == "ip"

    def test_kasada(self):
        sig = detectors.classify(403, {"x-kpsdk-ct": "1"}, "")
        assert sig.vendor == "kasada"

    def test_cn_markers(self):
        sig = detectors.classify(200, {}, '{"data": {"v_voucher": "v_1"}}')
        assert sig.vendor == "bilibili"
        marker = "操作过于频繁，请稍后再试"  # noqa: RUF001 — real XHS marker
        sig = detectors.classify(200, {}, marker)
        assert sig.vendor == "xhs"
        sig = detectors.classify(200, {}, "请完成人机验证")
        assert sig.vendor == "zhihu"

    def test_youtube_wall(self):
        sig = detectors.classify(403, {}, "Sign in to confirm you're not a bot")
        assert sig.vendor == "youtube"

    def test_generic_429(self):
        sig = detectors.classify(429, {}, "")
        assert sig.vendor == "generic" and sig.level == "ip"

    def test_clean_response(self):
        assert detectors.classify(200, {"content-type": "application/json"},
                                  '{"results": []}') is None


def classifiers_helper(status, headers, body):
    return detectors.classify(status, headers, body)


class TestLadder:
    def test_ladder_rungs(self):
        cf = detectors.BlockSignal("cloudflare", "transient", "x")
        assert detectors.ladder_action(cf, attempts=0) == "retry"
        assert detectors.ladder_action(cf, attempts=1) == "skip"
        ip = detectors.BlockSignal("generic", "ip", "429")
        assert detectors.ladder_action(ip, attempts=0) == "throttle"
        assert detectors.ladder_action(ip, attempts=2) == "rotate_ip"
        acct = detectors.BlockSignal("zhihu", "account", "x")
        assert detectors.ladder_action(acct, attempts=0) == "rotate_profile"
        assert detectors.ladder_action(acct, attempts=0,
                                       profile_quarantined=True) == "quarantine"
        assert detectors.ladder_action(None, attempts=0) == "none"


# --- fingerprints.py ----------------------------------------------------

class TestFingerprints:
    def test_derive_us_is_coherent(self):
        bundle = fingerprints.derive_for_geo("US")
        assert bundle["timezone"] == "America/New_York"
        assert bundle["locale"] == "en-US"
        assert fingerprints.lint(bundle) == []

    def test_tz_mismatch_flagged(self):
        bundle = fingerprints.derive_for_geo("JP")
        bundle["timezone"] = "Europe/Paris"
        problems = fingerprints.lint(bundle)
        assert any("contradicts country" in p for p in problems)

    def test_mobile_ua_desktop_screen_flagged(self):
        bundle = fingerprints.derive_for_geo("US")
        bundle["ua"] = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)"
        bundle["viewport"] = {"width": 1920, "height": 1080}
        problems = fingerprints.lint(bundle)
        assert any("desktop viewport" in p for p in problems)

    def test_unknown_country_passes_through(self):
        bundle = fingerprints.derive_for_geo("XK")
        assert "timezone" not in bundle
        assert fingerprints.lint(bundle) == []


# --- scheduler.py -------------------------------------------------------

class TestScheduler:
    def test_jitter_bounds(self):
        for _ in range(200):
            v = scheduler.jitter(10.0)
            assert 7.0 <= v <= 13.0
        assert scheduler.jitter(0) == 0.0
        assert scheduler.jitter(0.1) == 0.25  # floor

    @pytest.mark.asyncio
    async def test_lease_acquires(self):
        async with scheduler.browser_lease("t"):
            pass

    @pytest.mark.asyncio
    async def test_paced_no_sleep_first_call(self):
        import asyncio
        t0 = asyncio.get_running_loop().time()
        await scheduler.paced("unique-name", 5.0)
        assert asyncio.get_running_loop().time() - t0 < 0.5


# --- router.py ----------------------------------------------------------

class TestRouter:
    def test_tiers(self):
        assert router.tiers_for("searxng") == ("api",)
        assert router.tiers_for("reddit") == ("browser",)
        assert router.tiers_for("unknown") == ("api", "cli", "browser")

    def test_costs(self):
        assert router.cost_of("api") == 1
        assert router.cost_of("cli") == 3
        assert router.cost_of("browser") == 10
        assert router.cost_of("nonsense") == 10

    def test_cheapest_viable(self):
        assert router.cheapest_viable_tier("searxng") == "api"
        assert router.cheapest_viable_tier("reddit", browser_allowed=False) == "api"
        assert router.cheapest_viable_tier("reddit") == "browser"

    def test_tier_plan_shape(self):
        plan = router.tier_plan(
            type("S", (), {"name": "twitter"})())
        assert plan[0][0] == "cli" and plan[0][1] == 3
        assert any(t == "browser" for t, _, _ in plan)


# --- profiles.py --------------------------------------------------------

class TestProfiles:
    def test_store_empty_falls_back(self):
        st = profiles_mod.ProfileStore([])
        assert st.profiles_for("twitter") == []

    def test_store_filters_by_platform(self):
        p1 = profiles_mod.Profile(name="tw-1", platform="twitter")
        p2 = profiles_mod.Profile(name="rd-1", platform="reddit")
        st = profiles_mod.ProfileStore([p1, p2])
        assert [p.name for p in st.profiles_for("twitter")] == ["tw-1"]

    def test_state_machine_transitions(self, rds):
        st = profiles_mod.ProfileStore([profiles_mod.Profile(
            name="p1", platform="x")])
        assert st.state("p1") == "healthy"
        st.report_failure("p1", "cloudflare")
        st.report_failure("p1", "cloudflare")
        # 3 failures (PLATFORM_BLOCK_LIMIT) → cooldown
        assert st.report_failure("p1", "cloudflare") == "cooldown"
        assert not st.available("p1")
        st.report_success("p1")
        assert st.state("p1") == "healthy"
        assert st.available("p1")

    def test_quarantine_after_repeated_cooldowns(self, rds):
        st = profiles_mod.ProfileStore([profiles_mod.Profile(
            name="q1", platform="x")])
        # three *consecutive* cooldown cycles (no success in between)
        for _ in range(profiles_mod.QUARANTINE_CYCLES):
            for _ in range(profiles_mod.FAIL_THRESHOLD):
                st.report_failure("q1", "kasada")
        assert st.state("q1") == "quarantined"

    def test_coherence_report(self):
        bad = profiles_mod.Profile(
            name="bad", platform="x",
            fingerprint=dict(fingerprints.derive_for_geo("US"),
                             timezone="Asia/Tokyo"))
        st = profiles_mod.ProfileStore([bad])
        assert any(st.coherence_report()["bad"])

    def test_default_profile(self):
        p = profiles_mod.default_profile("twitter")
        assert p.platform == "twitter" and p.user_data_dir


# --- proxies.py ---------------------------------------------------------

class TestProxies:
    def test_disabled_by_default(self):
        assert not proxies_mod.enabled()
        assert proxies_mod.context_proxy("p") is None
        assert proxies_mod.jina_header() is None

    def test_username_grammar(self, monkeypatch):
        monkeypatch.setattr(proxies_mod, "PROXY_ENABLED", True)
        monkeypatch.setattr(proxies_mod, "PROXY_GATEWAY", "gw:8080")
        monkeypatch.setattr(proxies_mod, "PROXY_USERNAME", "")
        monkeypatch.setattr(proxies_mod, "PROXY_COUNTRY", "US")
        monkeypatch.setattr(proxies_mod, "PROXY_STICKY_TTL", "30m")
        proxy = proxies_mod.context_proxy("tw-1")
        assert proxy["server"] == "http://gw:8080"
        assert proxy["username"].startswith("US-sid-")
        assert proxy["username"].endswith("-ttl-30m")
        # sticky id is stable per profile
        assert proxies_mod.context_proxy("tw-1")["username"] == proxy["username"]
        assert proxies_mod.context_proxy("tw-2")["username"] != proxy["username"]

    def test_verbatim_username_wins(self, monkeypatch):
        monkeypatch.setattr(proxies_mod, "PROXY_ENABLED", True)
        monkeypatch.setattr(proxies_mod, "PROXY_GATEWAY", "gw:8080")
        monkeypatch.setattr(proxies_mod, "PROXY_USERNAME", "user-custom")
        assert proxies_mod.context_proxy("p")["username"] == "user-custom"

    def test_align_bundle_noop_when_disabled(self):
        bundle = fingerprints.derive_for_geo("JP")
        assert proxies_mod.align_bundle(bundle, "US") is bundle

    def test_align_bundle_aligns_when_enabled(self, monkeypatch):
        monkeypatch.setattr(proxies_mod, "PROXY_ENABLED", True)
        monkeypatch.setattr(proxies_mod, "PROXY_GATEWAY", "gw:8080")
        bundle = fingerprints.derive_for_geo("JP")
        aligned = proxies_mod.align_bundle(bundle, "US")
        assert aligned["timezone"] == "America/New_York"
        assert aligned["country"] == "US"
        assert fingerprints.lint(aligned) == []

    def test_health(self, rds, monkeypatch):
        monkeypatch.setattr(proxies_mod, "PROXY_ENABLED", True)
        monkeypatch.setattr(proxies_mod, "PROXY_GATEWAY", "gw:8080")
        proxies_mod.record_success("p")
        proxies_mod.record_failure("p")
        h = proxies_mod.health("p")
        assert h["total"] == 2 and h["errors"] == 1 and h["reliability"] == 0.5


# --- http.py ------------------------------------------------------------

class TestHttp:
    def test_should_impersonate_off_by_default(self):
        from kortex_search.extract import http
        assert not http._should_impersonate("bilibili")

    @pytest.mark.asyncio
    async def test_get_json_httpx_path(self, respx_mock):
        from kortex_search.extract import http
        respx_mock.get("https://example.test/x").respond(
            200, json={"ok": True})
        data = await http.get_json("https://example.test/x", source="searxng")
        assert data == {"ok": True}

    def test_response_raise_for_status(self):
        from kortex_search.extract.http import HTTPStatusError, Response
        with pytest.raises(HTTPStatusError):
            Response(404, {}, "").raise_for_status()


# --- envelope signals (orchestrator helpers) ------------------------------

class TestEnvelopeSignals:
    def test_blocked_parsing(self):
        import kortex_search.orchestrator as orch
        blocked, auth = orch._extract_signals({
            "twitter": "blocked (cloudflare/transient): cf-mitigated: challenge",
            "youtube": "ok (5)",
        })
        assert blocked == [{"source": "twitter", "vendor": "cloudflare",
                            "level": "transient"}]
        assert auth == {}

    def test_auth_missing_and_ok(self):
        import kortex_search.orchestrator as orch
        blocked, auth = orch._extract_signals({
            "zhihu": "auth: ZHIHU_COOKIE not set (zhihu blocks anonymous "
                     "API access with HTTP 401)",
            "weibo": "ok (10)",
            "reddit": "pending (timeout)",
        })
        assert auth == {"zhihu": "missing", "weibo": "ok", "reddit": "unknown"}
        assert blocked == []

    def test_list_outcomes_are_ok(self):
        import kortex_search.orchestrator as orch
        _, auth = orch._extract_signals({
            "twitter": [{"title": "t", "url": "u"}],
            "zhihu": "error: SourceError: boom",
        })
        assert auth == {"twitter": "ok", "zhihu": "unknown"}

    def test_extract_tiers_declared(self):
        import kortex_search.orchestrator as orch
        tiers = orch._extract_tiers(["searxng", "reddit", "zhihu"])
        assert tiers == {"searxng": {"tier": "api"},
                         "reddit": {"tier": "browser"},
                         "zhihu": {"tier": "api"}}


# --- camoufox adapter (lazy import, mocked) ---------------------------------

class TestCamoufox:
    def test_disabled_by_default(self, monkeypatch):
        import kortex_search.extract.camoufox as cf
        monkeypatch.setattr(cf, "STEALTH_ENABLED", False)
        ok, reason = cf.available()
        assert not ok and "disabled" in reason
        import asyncio
        browser, why = asyncio.run(cf.launch("p"))
        assert browser is None and "disabled" in why

    def test_missing_package(self, monkeypatch):
        import kortex_search.extract.camoufox as cf
        monkeypatch.setattr(cf, "STEALTH_ENABLED", True)
        monkeypatch.setitem(__import__("sys").modules, "camoufox", None)
        ok, reason = cf.available()
        assert not ok and "not installed" in reason

    @pytest.mark.asyncio
    async def test_launch_failure_degrades(self, monkeypatch):
        import kortex_search.extract.camoufox as cf
        from kortex_search.extract import harden
        monkeypatch.setattr(cf, "STEALTH_ENABLED", True)
        # 0.4.2: enforcement gates the launch — simulate a hardened env so the
        # test exercises the launch path itself
        monkeypatch.setattr(harden, "HARDEN", "permissive")

        class Boom:
            def __init__(self, **kw):
                raise RuntimeError("boom")

        monkeypatch.setitem(__import__("sys").modules, "camoufox", None)
        # simulate importable but failing launch
        import types
        fake = types.ModuleType("camoufox")
        fake.AsyncCamoufox = Boom
        monkeypatch.setitem(__import__("sys").modules, "camoufox", fake)
        browser, why = await cf.launch("p")
        assert browser is None and "boom" in why

    @pytest.mark.asyncio
    async def test_html_returns_none_without_browser(self):
        import kortex_search.extract.camoufox as cf
        assert await cf.html(None, "https://x") is None

    @pytest.mark.asyncio
    async def test_launch_returns_started_browser_and_forced_proxy_args(self,
                                                                        monkeypatch):
        # live-verified API contract (2026-08-25): AsyncCamoufox.start()
        # RETURNS the Playwright Browser — the adapter must return that, and
        # the L2 forced-proxy args must be attached when the proxy is on
        import kortex_search.extract.camoufox as cf
        from kortex_search.extract import harden
        monkeypatch.setattr(cf, "STEALTH_ENABLED", True)
        monkeypatch.setattr(harden, "HARDEN", "permissive")
        monkeypatch.setattr(cf, "EGRESS_PROXY", True)

        import types

        class FakeEgress:
            port = 4444

        async def fake_get_proxy():
            return FakeEgress()

        monkeypatch.setattr(cf, "get_proxy", fake_get_proxy)

        class FakeBrowser:
            pass

        fake = types.ModuleType("camoufox")

        class FakeAsyncCamoufox:
            kw: dict = {}  # noqa: RUF012 — test holder

            def __init__(self, **kw):
                FakeAsyncCamoufox.kw = kw

            async def start(self):
                return FakeBrowser()

        fake.AsyncCamoufox = FakeAsyncCamoufox
        monkeypatch.setitem(__import__("sys").modules, "camoufox", fake)

        browser, why = await cf.launch("p")
        assert why == ""
        assert isinstance(browser, FakeBrowser)  # start()'s return value
        started = FakeAsyncCamoufox.kw
        assert started["args"] == [
            "--proxy-server=http://127.0.0.1:4444",
            "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1",
        ]
        assert "proxy" not in started  # the egress proxy chains upstream itself

    @pytest.mark.asyncio
    async def test_default_headless_is_native(self, monkeypatch):
        # live-verified: headless=True needs no Xvfb; "virtual" does
        import kortex_search.extract.camoufox as cf
        from kortex_search.extract import harden
        monkeypatch.setattr(cf, "STEALTH_ENABLED", True)
        monkeypatch.setattr(harden, "HARDEN", "permissive")

        import types

        fake = types.ModuleType("camoufox")

        class FakeAsyncCamoufox:
            def __init__(self, **kw):
                FakeAsyncCamoufox.kw = kw

            async def start(self):
                return object()

        fake.AsyncCamoufox = FakeAsyncCamoufox
        monkeypatch.setitem(__import__("sys").modules, "camoufox", fake)
        await cf.launch("p")
        assert FakeAsyncCamoufox.kw["headless"] is True


# --- parse.py llm_assist + shape ladder -------------------------------------

class TestParseShapesLadder:
    @pytest.mark.asyncio
    async def test_llm_assist_gated(self, monkeypatch):
        from kortex_search.extract import parse as ext_parse
        monkeypatch.setattr(ext_parse, "LLM_PARSE", False)
        assert await ext_parse.llm_assist("x", "hint") == []

    @pytest.mark.asyncio
    async def test_llm_assist_no_llm(self, monkeypatch):
        from kortex_search import llm
        from kortex_search.extract import parse as ext_parse
        monkeypatch.setattr(ext_parse, "LLM_PARSE", True)
        monkeypatch.setattr(llm, "available", lambda: False)
        assert await ext_parse.llm_assist("x", "hint") == []

    @pytest.mark.asyncio
    async def test_llm_assist_validates_schema(self, monkeypatch):
        from kortex_search import llm
        from kortex_search.extract import parse as ext_parse
        monkeypatch.setattr(ext_parse, "LLM_PARSE", True)
        monkeypatch.setattr(llm, "available", lambda: True)

        async def fake_complete(*a, **k):
            return '[{"title": "T", "url": "https://u", "snippet": "s"}, ' \
                   '{"title": 1}]'

        monkeypatch.setattr(llm, "complete", fake_complete)
        out = await ext_parse.llm_assist("x", "hint")
        assert out == [{"title": "T", "url": "https://u",
                        "snippet": "s", "published": ""}]

    @pytest.mark.asyncio
    async def test_llm_assist_bad_json(self, monkeypatch):
        from kortex_search import llm
        from kortex_search.extract import parse as ext_parse
        monkeypatch.setattr(ext_parse, "LLM_PARSE", True)
        monkeypatch.setattr(llm, "available", lambda: True)

        async def fake_complete(*a, **k):
            return "no array here"

        monkeypatch.setattr(llm, "complete", fake_complete)
        assert await ext_parse.llm_assist("x", "hint") == []

    @pytest.mark.asyncio
    async def test_jsonld_fallback(self):
        from kortex_search.extract import parse as ext_parse
        html = ('<script type="application/ld+json">'
                '{"headline": "H", "url": "https://h", "description": "d"}'
                '</script>')
        out = await ext_parse.parse_shapes(html, source="s")
        assert len(out) == 1 and out[0].title == "H"

    @pytest.mark.asyncio
    async def test_css_fallback(self):
        from kortex_search.extract import parse as ext_parse
        html = '<a class="t" href="/1">One</a><a class="t" href="/2">Two</a>'
        out = await ext_parse.parse_shapes(
            html, source="s", css_rules=[("a.t", "title", ""),
                                         ("a.t", "url", "href")])
        assert [r.title for r in out] == ["One", "Two"]

    @pytest.mark.asyncio
    async def test_regex_fallback(self):
        from kortex_search.extract import parse as ext_parse
        out = await ext_parse.parse_shapes(
            "A: apple\nB: banana", source="s",
            regex_patterns=[(r"^A: (.+)$", "title", "1"),
                            (r"^B: (.+)$", "snippet", "1")])
        assert out[0].title == "apple" and out[0].snippet == "banana"


# --- profiles.py disk load + status -----------------------------------------

class TestProfilesDisk:
    def test_loads_json_list_from_dir(self, monkeypatch, tmp_path):
        import json as _json

        import kortex_search.extract.profiles as pf
        (tmp_path / "defs.json").write_text(_json.dumps([
            {"name": "tw-1", "platform": "twitter",
             "user_data_dir": "~/.agent-reach/profiles/tw1"},
            {"name": "rd-1", "platform": "reddit"},
        ]), encoding="utf-8")
        monkeypatch.setattr(pf, "PROFILE_DIR", str(tmp_path))
        st = pf.ProfileStore()
        assert {p.name for p in st.profiles_for("twitter")} == {"tw-1"}
        assert "rd-1" in [p.name for p in st.profiles_for("reddit")]

    def test_skips_malformed_json(self, monkeypatch, tmp_path):
        import kortex_search.extract.profiles as pf
        (tmp_path / "bad.json").write_text("{broken", encoding="utf-8")
        monkeypatch.setattr(pf, "PROFILE_DIR", str(tmp_path))
        st = pf.ProfileStore()
        assert st.profiles_for("anything") == []

    def test_from_dict_defaults(self):
        from kortex_search.extract.profiles import Profile
        p = Profile.from_dict({"name": "n", "platform": "x"})
        assert p.persona == "kaiser" and p.user_data_dir == ""
        assert p.fingerprint == {} and p.proxy == {}

    def test_status_and_available(self, rds):
        import kortex_search.extract.profiles as pf
        st = pf.ProfileStore([pf.Profile(name="p1", platform="x")])
        assert st.available("p1") is True
        st.report_failure("p1", "cf")
        st.report_failure("p1", "cf")
        st.report_failure("p1", "cf")  # → cooldown
        assert st.available("p1") is False
        status = st.status()
        assert status["p1"]["state"] == "cooldown"
        assert status["p1"]["fails"] == 3
