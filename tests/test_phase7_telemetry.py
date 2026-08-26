"""Phase 7 telemetry: block reservoir, doctor sections, envelope wiring."""

from __future__ import annotations

import pytest


class TestBlockReservoir:
    def test_record_and_snapshot(self, rds):
        from kortex_search import stats

        stats.record_block("twitter", "cloudflare", "transient")
        stats.record_block("twitter", "cloudflare", "transient")
        stats.record_block("reddit", "datadome", "ip")
        bl = stats.blocks_snapshot()
        assert bl["counters"] == {"twitter:cloudflare": 2, "reddit:datadome": 1}
        assert bl["total"] == 3
        assert bl["recent"][-1] == {"source": "reddit", "vendor": "datadome",
                                    "level": "ip", "ts": bl["recent"][-1]["ts"]}

    def test_reservoir_bounded(self, rds, monkeypatch):
        from kortex_search import stats

        monkeypatch.setattr(stats, "BLOCK_RESERVOIR", 3)
        for _i in range(10):
            stats.record_block("s", "v", "ip")
        bl = stats.blocks_snapshot()
        assert len(bl["recent"]) == 3
        assert bl["counters"]["s:v"] == 10  # counter unaffected by bound

    def test_snapshot_never_raises(self, monkeypatch):
        import redis as redis_mod

        from kortex_search import stats

        class Boom:
            def pipeline(self):
                raise redis_mod.RedisError("nope")

            def scan_iter(self, _pattern):
                raise redis_mod.RedisError("nope")

            def lrange(self, *_a):
                raise redis_mod.RedisError("nope")

        monkeypatch.setattr(stats, "_get_client", lambda: Boom())
        stats.record_block("s", "v", "ip")  # must not raise
        assert stats.blocks_snapshot() == {"counters": {}, "total": 0, "recent": []}


class TestBlockedErrorTelemetry:
    pytestmark = pytest.mark.asyncio

    async def test_run_cmd_records_raise_site(self, rds, monkeypatch):
        from kortex_search import stats
        from kortex_search.sources import base as sb

        sig = sb.classify(403, {"cf-mitigated": "challenge"}, None)
        assert sig is not None
        monkeypatch.setattr(sb, "BLOCK_DETECTION", True)
        err = sb._blocked_error(403, "<html>Just a moment...</html>", "twitter")
        assert err is not None and "blocked (cloudflare/transient)" in str(err)
        bl = stats.blocks_snapshot()
        assert bl["counters"].get("twitter:cloudflare", 0) == 1


class TestEnvelopeWiring:
    def test_non_raising_blocked_string_recorded(self, rds, monkeypatch):
        from kortex_search import stats
        from kortex_search.orchestrator import _extract_signals

        statuses = {
            "reddit": "blocked (datadome/ip): challenge page",  # non-raising
            "twitter": "error: blocked (cloudflare/transient): wall",
        }
        blocked, _auth = _extract_signals(statuses)
        assert len(blocked) == 2
        bl = stats.blocks_snapshot()
        # only the non-raising string records here; the error-prefixed one was
        # already recorded at the raise site (no double counting)
        assert bl["counters"] == {"reddit:datadome": 1}

    def test_error_prefixed_not_recorded_again(self, rds):
        from kortex_search import stats
        from kortex_search.orchestrator import _extract_signals

        _extract_signals({"twitter": "error: blocked (cf/ip): x"})
        assert stats.blocks_snapshot()["counters"] == {}


class TestDoctorSections:
    pytestmark = pytest.mark.asyncio
    async def test_four_new_sections_present(self, rds, monkeypatch):
        from kortex_search import health

        monkeypatch.setattr(health, "DOCTOR_TIMEOUT", 1)
        monkeypatch.setattr(health, "DOCTOR_PROBE_TIMEOUT", 0.2)
        monkeypatch.setattr(health, "_probe_cache", {})
        monkeypatch.setattr(health.stats, "ledger_health", dict)
        monkeypatch.setattr(health.cache, "ping", lambda: {"ok": True})
        monkeypatch.setattr(health.rerank, "status", dict)
        monkeypatch.setattr(health.emb, "status", dict)
        monkeypatch.setattr(health.llm, "available", lambda: False)

        class DummySource:
            async def available(self):
                return True, ""

        monkeypatch.setattr(health, "ALL_SOURCES", {"dummy": DummySource()})

        out = await health.report()
        assert set(out) >= {"egress", "vault", "blocks", "profiles"}

    async def test_egress_denials_reflected_in_doctor(self, rds, monkeypatch):
        from kortex_search import health, stats

        stats.record_block("egress", "floor", "169.254.0.0/16")
        monkeypatch.setattr(health, "DOCTOR_TIMEOUT", 1)
        monkeypatch.setattr(health, "DOCTOR_PROBE_TIMEOUT", 0.2)
        monkeypatch.setattr(health, "_probe_cache", {})
        monkeypatch.setattr(health.stats, "ledger_health", dict)
        monkeypatch.setattr(health.cache, "ping", lambda: {"ok": True})
        monkeypatch.setattr(health.rerank, "status", dict)
        monkeypatch.setattr(health.emb, "status", dict)
        monkeypatch.setattr(health.llm, "available", lambda: False)

        class DummySource:
            async def available(self):
                return True, ""

        monkeypatch.setattr(health, "ALL_SOURCES", {"dummy": DummySource()})

        out = await health.report()
        assert out["egress"]["denied_count"] == 1
        assert out["egress"]["last_denial"]["source"] == "egress"


class TestStatsReportTool:
    pytestmark = pytest.mark.asyncio
    async def test_stats_report_gains_blocks(self, rds, monkeypatch):
        from kortex_search import server, stats

        monkeypatch.setattr(stats, "ledger_health", dict)
        stats.record_block("v2ex", "generic", "ip")
        out = await server.stats_report()
        assert out["blocks"]["counters"].get("v2ex:generic") == 1
        assert out["_ledger"] == {}
