"""Pipeline + remaining-module coverage: orchestrator.search end-to-end with
fake sources (no models), openalex get/citations/references, rerank load
paths, server tool dispatches, llm/cache/dedup/diversity edges."""

from __future__ import annotations

import asyncio

import pytest

from kortex_search.models import Result
from kortex_search.sources.base import Source


class FakeSource(Source):
    def __init__(self, name, results, source_type="web", delay=0.0):
        self.name = name
        self._results = results
        self.source_type = source_type
        self._delay = delay

    async def search(self, query, limit=10, **kwargs):
        if self._delay:
            await asyncio.sleep(self._delay)
        return [Result(**{**r, "source": self.name}) for r in self._results][:limit]


def _mk(title, url, published=None):
    return {"title": title, "url": url, "snippet": "snip", "published": published}


# --------------------------------------------------------------------------
# orchestrator.search pipeline (models off)
# --------------------------------------------------------------------------

def test_orchestrator_search_pipeline(monkeypatch, rds):
    import kortex_search.orchestrator as omod
    from kortex_search import orchestrator as orch

    monkeypatch.setattr(omod, "SEMANTIC_RERANK", False)
    monkeypatch.setattr(omod, "EMBEDDING_DEDUP", False)
    monkeypatch.setattr(omod, "MMR_ENABLED", False)
    monkeypatch.setattr(omod, "QUERY_EXPANSION", False)

    monkeypatch.setattr(omod, "get_sources", lambda names: [FakeSource(n, []) for n in names])

    async def run():
        # full path: two sources, one dedup collision by URL
        s1 = FakeSource("s1", [_mk("Shared Title", "https://x.com/1")])
        s2 = FakeSource("s2", [_mk("Shared Title", "https://x.com/1")])

        monkeypatch.setattr(omod, "get_sources", lambda names: [s1, s2])
        out = await orch.search("test query", ["s1", "s2"], limit=5)
        assert out["cached"] is False
        assert out["count"] == 1  # URL-deduped
        assert out["sources"]["s1"].startswith("ok")
        assert "elapsed_ms" in out
        # second call → final cache hit
        out2 = await orch.search("test query", ["s1", "s2"], limit=5)
        assert out2["cached"] is True

        # pending (timeout) source path
        slow = FakeSource("slow", [_mk("T", "https://s.com/1")], delay=0.2)
        fast = FakeSource("fast", [_mk("F", "https://f.com/1")])

        monkeypatch.setattr(omod, "get_sources", lambda names: [slow, fast])
        monkeypatch.setattr(omod, "GLOBAL_TIMEOUT", 0.05)
        out3 = await orch.search("timeout test", ["slow", "fast"], limit=5)
        assert out3["partial"] is True
        assert "slow" in out3["pending"] or "slow" in out3["sources"]

        # per-source freshness + year + oa filters
        old = _mk("Old", "https://o.com/1", published="2020-01-01")
        fresh = _mk("Fresh", "https://n.com/1", published="2026-08-20")
        undated = _mk("Undated", "https://u.com/1")
        f = FakeSource("f", [old, fresh, undated])

        monkeypatch.setattr(omod, "get_sources", lambda names: [f])
        out4 = await orch.search("fresh", ["f"], limit=5, freshness="week")
        titles = [r["title"] for r in out4["results"]]
        assert "Old" not in titles
        assert titles.count("Fresh") == 1
        assert titles.count("Undated") == 1  # no duplication (C1 regression)

        # source error path
        class BrokenSource(Source):
            name = "broken"

            async def search(self, query, limit=10, **kwargs):
                raise RuntimeError("boom")

        monkeypatch.setattr(omod, "get_sources", lambda names: [BrokenSource()])
        out5 = await orch.search("broken query", ["broken"], limit=5)
        assert "error" in out5["sources"]["broken"]

    asyncio.run(run())


def test_filter_year_and_oa():
    from kortex_search.orchestrator import _filter_oa, _filter_year
    r1 = Result(title="a", url="https://a.com/", meta={"year": 2026, "is_oa": True})
    r2 = Result(title="b", url="https://b.com/", meta={"year": 2020, "is_oa": False})
    r3 = Result(title="c", url="https://c.com/", meta={})
    assert [r.title for r in _filter_year([r1, r2, r3], 2025)] == ["a", "c"]
    assert [r.title for r in _filter_oa([r1, r2, r3])] == ["a", "c"]


def test_filter_key_parts():
    from kortex_search.orchestrator import _filter_key
    assert _filter_key("week", None, False) == "fr:week"
    assert _filter_key(None, 2025, True) == "yr:2025|oa"
    assert _filter_key(None, None, False) == ""


# --------------------------------------------------------------------------
# openalex get/citations/references (shared fake client)
# --------------------------------------------------------------------------

class FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {}

    @property
    def text(self):
        import json as _json
        return _json.dumps(self._payload) if self._payload is not None else ""

    def raise_for_status(self):
        if self.status_code >= 400:
            from kortex_search.extract.http import HTTPStatusError
            raise HTTPStatusError(self.status_code)

    def json(self):
        return self._payload


class SharedFakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self._last = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def _next(self):
        if self.responses:
            self._last = self.responses.pop(0)
        return self._last

    async def get(self, url, **kwargs):
        self.calls.append(url)
        return await self._next()

    async def request(self, method, url, **kwargs):
        self.calls.append(url)
        return await self._next()


OA_PAPER = {"title": "P", "id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/p",
            "publication_date": "2026-01-01", "publication_year": 2026, "authorships": [],
            "primary_location": None, "open_access": {}, "cited_by_count": 0,
            "abstract_inverted_index": None}


def _patch_oa(monkeypatch, responses):
    import httpx as _httpx
    client = SharedFakeClient(responses)
    monkeypatch.setattr(_httpx, "AsyncClient", lambda **kw: client)
    return client


def test_openalex_get_doi(monkeypatch):
    from kortex_search.sources import ALL_SOURCES
    _patch_oa(monkeypatch, [FakeResp(OA_PAPER)])

    async def run():
        r = await ALL_SOURCES["openalex"].get("10.1/p")
        assert r.meta["paper_id"] == "W1"

    asyncio.run(run())


def test_openalex_citations_and_references(monkeypatch):
    from kortex_search.sources import ALL_SOURCES
    # citations: resolve (W already an ID → short-circuit, no call) + cite list
    client = _patch_oa(monkeypatch, [FakeResp({"results": [OA_PAPER]})])
    async def run():
        cites = await ALL_SOURCES["openalex"].citations("W1", limit=5)
        assert len(cites) == 1
        assert len(client.calls) == 1  # no resolve call for bare W-id
        # references: resolve (doi → 1 call) + work (1 call) + batch (1 call)
        client2 = _patch_oa(monkeypatch, [
            FakeResp({"id": "https://openalex.org/W1"}),
            FakeResp({"referenced_works": ["https://openalex.org/W2", "https://openalex.org/W3"]}),
            FakeResp({"results": [OA_PAPER]}),
        ])
        refs = await ALL_SOURCES["openalex"].references("10.1/p", limit=5)
        assert len(refs) == 1
        assert len(client2.calls) == 3
        # arxiv doi resolution path
        client3 = _patch_oa(monkeypatch, [
            FakeResp({"id": "https://openalex.org/W9"}),
            FakeResp({"results": []}),
        ])
        await ALL_SOURCES["openalex"].citations("2603.12345", limit=5)
        # the identifier-injection fix quotes the path segment
        assert "doi:10.48550%2Farxiv.2603.12345" in client3.calls[0]

    asyncio.run(run())


# --------------------------------------------------------------------------
# rerank model load paths
# --------------------------------------------------------------------------

def test_rerank_torch_load_success(monkeypatch):
    import sentence_transformers as st

    from kortex_search import rerank
    monkeypatch.setattr(rerank, "_model", None)
    monkeypatch.setattr(rerank, "_model_error", None)
    monkeypatch.setattr(rerank, "INFERENCE_BACKEND", "torch")

    class FakeCE:
        def __init__(self, *a, **kw):
            pass

        def predict(self, pairs):
            return [0.9, 0.1]

    monkeypatch.setattr(st, "CrossEncoder", FakeCE)
    model = rerank._get_model()
    assert isinstance(model, FakeCE)


def test_rerank_onnx_fallback_to_torch(monkeypatch):
    from kortex_search import rerank
    monkeypatch.setattr(rerank, "_model", None)
    monkeypatch.setattr(rerank, "_model_error", None)
    monkeypatch.setattr(rerank, "INFERENCE_BACKEND", "onnx_int8")

    class ExplodingCE:
        def __init__(self, *a, **kw):
            if kw.get("backend") == "onnx":
                raise RuntimeError("onnx unavailable")

    class TorchCE:
        def __init__(self, *a, **kw):
            pass

    import sentence_transformers as st
    monkeypatch.setattr(st, "CrossEncoder", ExplodingCE)
    model = rerank._get_model()
    assert model is not None
    assert rerank._effective_model == rerank.RERANK_MODEL


def test_rerank_total_failure_caches_error(monkeypatch):
    from kortex_search import rerank
    monkeypatch.setattr(rerank, "_model", None)
    monkeypatch.setattr(rerank, "_model_error", None)
    monkeypatch.setattr(rerank, "INFERENCE_BACKEND", "torch")
    import sentence_transformers as st
    monkeypatch.setattr(st, "CrossEncoder",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no models")))
    model = rerank._get_model()
    assert model is None
    assert rerank._model_error is not None


# --------------------------------------------------------------------------
# server tool dispatches (orchestrator mocked)
# --------------------------------------------------------------------------

def _mock_orchestrator_search(monkeypatch, results=None):
    from kortex_search import server

    async def fake_search(query, sources=None, **kw):
        return {"query": query, "results": results or [], "count": len(results or []),
                "sources": {s: "ok (0)" for s in (sources or [])}, "cached": False,
                "reranked": False, "partial": False, "pending": [], "elapsed_ms": 1}

    monkeypatch.setattr(server.orchestrator, "search", fake_search)
    return server


def test_server_search_tool_dispatch(monkeypatch):
    server = _mock_orchestrator_search(monkeypatch)
    results = [Result(title="t", url="https://t.com/", source="searxng").to_dict()]

    async def fake_search(query, sources=None, **kw):
        return {"query": query, "results": results, "count": 1,
                "sources": {s: "ok (1)" for s in (sources or [])}, "cached": False,
                "reranked": False, "partial": False, "pending": [], "elapsed_ms": 1}

    monkeypatch.setattr(server.orchestrator, "search", fake_search)

    async def run():
        assert (await server.search("q"))["count"] == 1
        assert (await server.search_web("q"))["count"] == 1
        assert (await server.search_news("q"))["count"] == 1
        assert (await server.search_science("q"))["count"] == 1
        assert (await server.search_academic("q"))["count"] == 1
        assert (await server.search_social("q"))["count"] == 1
        out = await server.search("q", limit=500)  # clamped
        assert out["count"] == 1

    asyncio.run(run())


def test_server_stats_and_doctor_tools(monkeypatch):
    from kortex_search import server

    async def run():
        assert isinstance(await server.stats_report(), dict)
        d = await server.doctor()
        assert "redis" in d

    asyncio.run(run())


def test_read_url_error(monkeypatch):
    from kortex_search import server
    from kortex_search.sources import ALL_SOURCES

    async def boom(url):
        raise RuntimeError("jina down")

    monkeypatch.setattr(ALL_SOURCES["web"], "read", boom)

    async def run():
        out = await server.read_url("https://example.com/")
        assert "error" in out

    asyncio.run(run())


# --------------------------------------------------------------------------
# llm.complete paths
# --------------------------------------------------------------------------

class FakePostResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            from httpx import HTTPError
            raise HTTPError(f"http {self.status_code}")

    def json(self):
        return self._payload


class FakeLLMClient:
    def __init__(self, responses=None, **kw):
        self.responses = list(responses or [])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        return self.responses.pop(0)


def test_llm_complete_success(monkeypatch):
    from kortex_search import llm
    monkeypatch.setattr(llm, "get_api_key", lambda: "k")
    monkeypatch.setattr(llm.httpx, "AsyncClient",
                        lambda **kw: FakeLLMClient([FakePostResp(
                            {"choices": [{"message": {"content": "the answer"}}]})]))

    async def run():
        out = await llm.complete([{"role": "user", "content": "q"}], max_tokens=100)
        assert out == "the answer"

    asyncio.run(run())


def test_llm_complete_error_paths(monkeypatch):
    from kortex_search import llm
    monkeypatch.setattr(llm, "get_api_key", lambda: "")

    async def run():
        with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
            await llm.complete([{"role": "user", "content": "q"}])
        monkeypatch.setattr(llm, "get_api_key", lambda: "k")
        monkeypatch.setattr(llm.httpx, "AsyncClient",
                            lambda **kw: FakeLLMClient([FakePostResp({}, status=500)]))
        with pytest.raises(RuntimeError, match="deepseek"):
            await llm.complete([{"role": "user", "content": "q"}])
        monkeypatch.setattr(llm.httpx, "AsyncClient",
                            lambda **kw: FakeLLMClient([FakePostResp({"error": "overloaded"})]))
        with pytest.raises(RuntimeError, match="API error"):
            await llm.complete([{"role": "user", "content": "q"}])
        monkeypatch.setattr(llm.httpx, "AsyncClient",
                            lambda **kw: FakeLLMClient([FakePostResp({"choices": []})]))
        assert await llm.complete([{"role": "user", "content": "q"}]) == ""

    asyncio.run(run())


# --------------------------------------------------------------------------
# cache / dedup / diversity edges
# --------------------------------------------------------------------------

def test_cache_get_set_ping(rds):
    from kortex_search import cache
    payload = [{"title": "t", "url": "https://t.com/"}]
    cache.set("q", ["s1"], "general", 5, payload)
    assert cache.get("q", ["s1"], "general", 5) == payload
    assert cache.get("q", ["s2"], "general", 5) is None
    assert cache.ping()["ok"] is True


def test_cache_bad_json(rds):
    from kortex_search import cache
    rds.set(cache._key("q", ["s1"], "general", 5), "not-json")
    assert cache.get("q", ["s1"], "general", 5) is None


def test_dedup_canonical_url():
    from kortex_search.dedup import canonical_url
    assert canonical_url("https://WWW.Example.com/a?utm_source=x&b=2") == \
        "https://example.com/a?b=2"
    assert canonical_url("") == ""
    assert canonical_url("plain string") == "http:plain string"  # urlparse quirk, kept defensively


def test_dedup_near_duplicate_and_merge():
    from kortex_search.dedup import dedup
    a = Result(title="Same Story", url="https://a.com/1", snippet="short")
    b = Result(title="Same Story!", url="https://b.com/1", snippet="much longer snippet",
               source="s2")
    out = dedup([a, b])
    assert len(out) == 1
    assert out[0].snippet == "much longer snippet"  # richer wins via merge
    assert "s2" in out[0].meta["_also_found_by"]


def test_mmr_select_full_path():
    import numpy as np

    from kortex_search.diversity import mmr_select
    res = [Result(title=f"r{i}", url=f"https://{i}.com/", score=0.9 - i * 0.01)
           for i in range(6)]
    emb = np.eye(6)
    out = mmr_select(res, emb, limit=3)
    assert len(out) == 3
    # n <= limit → unchanged
    assert mmr_select(res[:2], None, limit=5) == res[:2]
    # below floor → skipped (greedy loop, n > limit)
    low = [Result(title="top", url="https://a.com/", score=1.0),
           Result(title="floor", url="https://b.com/", score=0.01),
           Result(title="floor2", url="https://c.com/", score=0.02),
           Result(title="floor3", url="https://d.com/", score=0.03)]
    assert len(mmr_select(low, None, limit=1)) == 1


# --------------------------------------------------------------------------
# embeddings (model loaders mocked — no real model downloads)
# --------------------------------------------------------------------------

def test_embeddings_load_and_encode(monkeypatch):
    import numpy as np
    import sentence_transformers as st

    from kortex_search import embeddings as emb

    class FakeST:
        def __init__(self, *a, **kw):
            self.kw = kw

        def encode(self, texts, **kw):
            return np.array([[1.0, 0.0]] * len(texts))

    monkeypatch.setattr(st, "SentenceTransformer", FakeST)
    monkeypatch.setattr(emb, "_model", None)
    monkeypatch.setattr(emb, "_model_error", None)
    monkeypatch.setattr(emb, "_cjk_model", None)
    monkeypatch.setattr(emb, "_cjk_model_error", None)

    m = emb._get_model()
    assert isinstance(m, FakeST)
    vecs = emb.encode(["hello world"])
    assert vecs is not None and vecs.shape == (1, 2)
    assert emb.cosine_matrix(vecs).shape == (1, 1)
    stt = emb.status()
    assert stt["loaded"] is True


def test_embeddings_cache_miss_download_path(monkeypatch):
    import sentence_transformers as st

    from kortex_search import embeddings as emb

    class FlakyST:
        def __init__(self, *a, **kw):
            if kw.pop("local_files_only", False):
                raise RuntimeError("not cached")
            self.kw = kw

        def encode(self, texts, **kw):
            import numpy as np
            return np.array([[1.0]] * len(texts))

    monkeypatch.setattr(st, "SentenceTransformer", FlakyST)
    import huggingface_hub as hf
    monkeypatch.setattr(hf, "snapshot_download",
                        lambda *a, **kw: "/fake/local/model")

    async def nothing():
        pass

    m, err = emb._load("some/model", revision="r1")
    assert m is not None
    assert err is None


def test_embeddings_load_failure_and_empty(monkeypatch):
    import sentence_transformers as st

    from kortex_search import embeddings as emb
    monkeypatch.setattr(emb, "_model", None)
    monkeypatch.setattr(emb, "_model_error", None)
    monkeypatch.setattr(emb, "_cjk_model", None)
    monkeypatch.setattr(emb, "_cjk_model_error", None)
    monkeypatch.setattr(st, "SentenceTransformer",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no models")))
    import huggingface_hub as hf
    monkeypatch.setattr(hf, "snapshot_download",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no net")))
    m, err = emb._load("some/model")
    assert m is None and err
    assert emb.encode([]) is None
    assert emb.encode(["x"]) is None  # no model → None


def test_embeddings_cjk_dominant_details():
    from kortex_search.embeddings import cjk_dominant
    assert cjk_dominant([]) is False
    assert cjk_dominant(["", ""]) is False
    assert cjk_dominant(["ひらがな", "한국어"]) is True  # kana + hangul counted
    assert cjk_dominant(["english only"]) is False
    assert cjk_dominant([None]) is False  # non-str tolerated? (str() not applied — empty)


# --------------------------------------------------------------------------
# remaining dedup/rerank/server edges
# --------------------------------------------------------------------------

def test_dedup_embedding_path():
    import numpy as np

    from kortex_search.dedup import dedup
    a = Result(title="Alpha", url="https://a.com/1", snippet="long english snippet here")
    b = Result(title="Alfa", url="https://b.com/1", snippet="long english snippet here")
    emb = np.array([[1.0, 0.0], [0.99, 0.01]])  # near-cosine 0.99 ≥ 0.93
    out = dedup([a, b], embeddings=emb)
    assert len(out) == 1
    # CJK docs skip embedding dedup (ASCII-dominant gate)
    c = Result(title="中文标题", url="https://c.com/1", snippet="中文内容中文内容")
    d = Result(title="中文标题二", url="https://d.com/2", snippet="中文内容中文内容")
    out2 = dedup([c, d], embeddings=emb)
    assert len(out2) == 2


def test_dedup_similar_edges():
    from kortex_search.dedup import _similar
    assert _similar("", "", 0.92) is False
    assert _similar("short", "short2", 0.92) is False  # min len 8
    assert _similar("exact match", "exact match", 0.92) is True
    assert _similar("aaaa bbbb cccc", "aaaa bbbb ccce", 0.92) is True
    assert _similar("abcdefgh", "xxxxxxxx", 0.92) is False


def test_rerank_predict_path(monkeypatch):
    from kortex_search import rerank

    class FakeModel:
        def predict(self, pairs):
            return [0.1, 0.9]

    monkeypatch.setattr(rerank, "SEMANTIC_RERANK", True)
    monkeypatch.setattr(rerank, "_get_model", lambda: FakeModel())
    res = [Result(title="b", url="https://b.com/", snippet="low"),
           Result(title="a", url="https://a.com/", snippet="high")]
    out = rerank.rerank("q", res)
    assert out[0].title == "a"  # highest score first
    assert out[0].score == 0.9


def test_rerank_predict_error_falls_back(monkeypatch):
    from kortex_search import rerank

    class BadModel:
        def predict(self, pairs):
            raise RuntimeError("inference failed")

    monkeypatch.setattr(rerank, "SEMANTIC_RERANK", True)
    monkeypatch.setattr(rerank, "_get_model", lambda: BadModel())
    res = [Result(title="a", url="https://a.com/")]
    assert rerank.rerank("q", res) == res


def test_server_saved_queries_dispatch_and_stats(monkeypatch, rds):
    from kortex_search import server

    async def run():
        out = await server.saved_queries(action="bogus")
        assert "unknown action" in out["error"]
        out2 = await server.saved_queries(action="list")
        assert isinstance(out2["queries"], list)

    asyncio.run(run())
