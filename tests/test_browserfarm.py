"""Managed profile farm tests — hermetic (no real browser, no real egress).

Covers the browserfarm supervisor (ensure/exec/health/shutdown/reap), the
run_profile source primitive, and the reddit/twitter fallback ladders.
"""

from __future__ import annotations

import asyncio

import pytest

from kortex_search.extract.profiles import Profile
from kortex_search.sources.base import SourceError


def _prof(name="p1", platform="reddit", persona="kaiser", udd="farmprof"):
    return Profile(name=name, platform=platform, persona=persona,
                   user_data_dir=udd)


# --------------------------------------------------------------------------
# supervisor primitives
# --------------------------------------------------------------------------

def test_parse_cdp_and_registry_roundtrip(monkeypatch, rds):
    import kortex_search.extract.browserfarm as farm

    monkeypatch.setattr(farm, "_get_client", lambda: rds)
    assert farm._parse_cdp('{"data":{"cdpUrl":"ws://127.0.0.1:9401/x"}}') \
        == "ws://127.0.0.1:9401/x"
    assert farm._parse_cdp("garbage") == ""
    farm._registry_set("p1", "ws://127.0.0.1:9401/x", 123.0)
    cdp, lastuse = farm._registry_get("p1")
    assert cdp == "ws://127.0.0.1:9401/x" and lastuse == 123.0
    farm._registry_delete("p1")
    assert farm._registry_get("p1") == ("", 0.0)


def test_ensure_returns_registered_when_alive(monkeypatch, rds):
    import kortex_search.extract.browserfarm as farm

    monkeypatch.setattr(farm, "_get_client", lambda: rds)
    monkeypatch.setattr(farm, "_cdp_alive", lambda cdp: asyncio.sleep(0, True))

    async def run():
        farm._registry_set("p1", "ws://127.0.0.1:9401/x", 100.0)
        ok, detail = await farm.ensure(_prof())
        return ok, detail

    ok, detail = asyncio.run(run())
    assert ok is True and detail == "ws://127.0.0.1:9401/x"


def test_ensure_refuses_without_egress_hardening(monkeypatch, rds):
    import kortex_search.extract.browserfarm as farm
    import kortex_search.extract.harden as harden

    monkeypatch.setattr(farm, "_get_client", lambda: rds)
    monkeypatch.setattr(farm, "_cdp_alive",
                        lambda cdp: asyncio.sleep(0, False))

    class _Refused(harden.EgressUnhardened):
        def __init__(self):
            super().__init__()

    def _refuse(require_coverage=False):
        raise _Refused()

    monkeypatch.setattr(harden, "enforce", _refuse)

    async def run():
        return await farm.ensure(_prof())

    ok, detail = asyncio.run(run())
    assert ok is False and detail != ""


def test_ensure_launches_and_registers_cdp(monkeypatch, rds, tmp_path):
    import kortex_search.extract.browserfarm as farm
    import kortex_search.extract.harden as harden

    monkeypatch.setattr(farm, "_get_client", lambda: rds)
    monkeypatch.setattr(farm, "_cdp_alive",
                        lambda cdp: asyncio.sleep(0, False))
    monkeypatch.setattr(harden, "enforce", lambda require_coverage=False: None)
    calls = []

    async def fake_spawn(argv, timeout, scope_name=""):
        calls.append(argv)
        if "cdp-url" in argv:
            return 0, '{"data":{"cdpUrl":"ws://127.0.0.1:9402/x"}}'
        return 0, "launched"

    monkeypatch.setattr(farm, "_spawn", fake_spawn)

    async def run():
        p = _prof(udd=str(tmp_path / "udd"))
        ok, detail = await farm.ensure(p)
        return ok, detail

    ok, detail = asyncio.run(run())
    assert ok is True and "9402" in detail
    joined = " ".join(" ".join(a) for a in calls)
    assert "--profile" in joined and "about:blank" in joined
    assert farm._registry_get("p1")[0] == "ws://127.0.0.1:9402/x"


def test_reap_idle_shuts_down_stale_profiles(monkeypatch, rds):
    import time

    import kortex_search.extract.browserfarm as farm

    monkeypatch.setattr(farm, "_get_client", lambda: rds)
    monkeypatch.setattr(farm, "FARM_IDLE_TTL", 100)
    closed = []

    async def fake_shutdown(p):
        closed.append(p.name)

    monkeypatch.setattr(farm, "shutdown", fake_shutdown)
    farm._registry_set("stale", "ws://x", time.time() - 500)
    farm._registry_set("fresh", "ws://y", time.time())

    async def run():
        return await farm.reap_idle([_prof("stale"), _prof("fresh")])

    reaped = asyncio.run(run())
    assert reaped == ["stale"]
    assert closed == ["stale"]


# --------------------------------------------------------------------------
# run_profile primitive
# --------------------------------------------------------------------------

def test_run_profile_success_path(monkeypatch, rds):
    import kortex_search.extract.browserfarm as farm
    import kortex_search.sources.base as base

    monkeypatch.setattr(farm, "_get_client", lambda: rds)

    async def fake_ensure(profile):
        return True, "ws://127.0.0.1:9403/x"

    async def fake_exec(profile, argv, timeout=45):
        assert argv[0] == "open"
        return 0, "[]"

    import kortex_search.config as cfg

    monkeypatch.setattr(farm, "ensure", fake_ensure)
    monkeypatch.setattr(farm, "exec_sync", fake_exec)
    monkeypatch.setattr(cfg, "RATE_LIMIT_INTERVAL", 0.0)

    async def run():
        return await base.run_profile(_prof(), ["open", "https://x"], source="reddit")

    code, out = asyncio.run(run())
    assert code == 0 and out == "[]"


def test_run_profile_raises_when_ensure_fails(monkeypatch, rds):
    import kortex_search.extract.browserfarm as farm
    import kortex_search.sources.base as base

    monkeypatch.setattr(farm, "_get_client", lambda: rds)

    async def fake_ensure(profile):
        return False, "egress unhardened"

    import kortex_search.config as cfg

    monkeypatch.setattr(farm, "ensure", fake_ensure)
    monkeypatch.setattr(cfg, "RATE_LIMIT_INTERVAL", 0.0)

    async def run():
        await base.run_profile(_prof(), ["open", "https://x"])

    with pytest.raises(SourceError, match="unavailable"):
        asyncio.run(run())


# --------------------------------------------------------------------------
# adapter ladders
# --------------------------------------------------------------------------

def test_reddit_farm_tier_returns_and_reports_success(monkeypatch, rds):
    import kortex_search.extract.profiles as profiles
    import kortex_search.sources.reddit as mod

    monkeypatch.setattr(mod, "FARM_ENABLED", True)
    monkeypatch.setattr(profiles, "store", profiles.ProfileStore(
        profiles=[_prof("p1")]))
    rds.set("ks:ph:p1:state", "healthy")

    async def fake_run_profile(profile, argv, source=None):
        return 0, ('[{"title":"Farm Post","url":"https://old.reddit.com/r/x/1",'
                   '"subreddit":"x","author":"a","score":5,"comments":2}]')

    monkeypatch.setattr(mod, "run_profile", fake_run_profile)

    async def run():
        return await mod.RedditSource().search("farm test", limit=5)

    out = asyncio.run(run())
    assert out[0].engine == "farm-cdp"
    assert out[0].title == "Farm Post"
    assert rds.get("ks:ph:p1:state") == "healthy"


def test_reddit_farm_fail_falls_back_to_opencli(monkeypatch, rds):
    import kortex_search.extract.profiles as profiles
    import kortex_search.sources.reddit as mod

    monkeypatch.setattr(mod, "FARM_ENABLED", True)
    new_store = profiles.ProfileStore(profiles=[_prof("p1")])
    monkeypatch.setattr(profiles, "store", new_store)
    monkeypatch.setattr(mod, "store", new_store)
    rds.set("ks:ph:p1:state", "healthy")

    async def failing_run_profile(profile, argv, source=None):
        raise SourceError("profile p1 unavailable: egress unhardened")

    async def fake_run_opencli(cmd, timeout=18, env=None, retries=1, source=None):
        return 0, '[{"title":"OCLI Post","url":"https://r/x","selftext":"s"}]'

    monkeypatch.setattr(mod, "run_profile", failing_run_profile)
    monkeypatch.setattr(mod, "run_opencli", fake_run_opencli)

    async def run():
        return await mod.RedditSource().search("fallback test", limit=5)

    out = asyncio.run(run())
    assert out[0].engine == "opencli"
    # failure recorded against the profile health machine
    assert rds.get("ks:ph:p1:fails") == "1"


def test_twitter_farm_tier_between_cli_and_opencli(monkeypatch, rds):
    import kortex_search.extract.profiles as profiles
    import kortex_search.sources.twitter as mod

    monkeypatch.setattr(mod, "FARM_ENABLED", True)
    monkeypatch.setattr(profiles, "store", profiles.ProfileStore(
        profiles=[_prof("t1", "twitter")]))
    rds.set("ks:ph:t1:state", "healthy")
    monkeypatch.setattr(mod, "_load_twitter_env", lambda: {})

    async def fake_run_profile(profile, argv, source=None):
        return 0, ('[{"text":"farm tweet","href":"/user/status/42",'
                   '"author":"u\\n@u"}]')

    monkeypatch.setattr(mod, "run_profile", fake_run_profile)

    async def run():
        return await mod.TwitterSource().search("farm tw", limit=5)

    out = asyncio.run(run())
    assert out[0].engine == "farm-cdp"
    assert out[0].url == "https://x.com/user/status/42"
