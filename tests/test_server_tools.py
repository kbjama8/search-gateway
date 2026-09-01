"""Server tool paths (get_paper/get_citations/get_references/research_answer/
saved_queries) + module edge coverage — hermetic, no network."""

from __future__ import annotations

import asyncio
import json

from kortex_search import saved_queries as sq
from kortex_search.models import Result
from kortex_search.server import (
    _normalize_identifier,
    _pick_fields,
    get_citations,
    get_paper,
    get_references,
)
from kortex_search.sources import ALL_SOURCES
from kortex_search.sources.base import SourceError


class FakeResp:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, responses=None, **kwargs):
        self.responses = list(responses or [])
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kwargs):
        self.calls.append(url)
        if self.responses:
            return self.responses.pop(0)
        return FakeResp({})


def _mock_http(monkeypatch, module, responses):
    """Patch a source module's extract.http primitives with a scripted queue.

    Each module gets its OWN client — responses stay deterministic per
    source (the global-httpx patch collides when two sources are patched in
    one test). Migrated sources call get_json/get_text/request by name.
    """
    client = FakeClient(responses)

    async def _checked(resp):
        from kortex_search.extract.http import HTTPStatusError
        if getattr(resp, "status_code", 200) >= 400:
            raise HTTPStatusError(resp.status_code)
        return resp

    async def fake_get_json(url, *, source=None, headers=None, params=None,
                            timeout=20.0):
        r = await client.get(url, params=params)
        return (await _checked(r)).json()

    async def fake_get_text(url, *, source=None, headers=None, params=None,
                            timeout=20.0):
        r = await client.get(url, params=params)
        return (await _checked(r)).text

    async def fake_request(method, url, *, source=None, headers=None,
                           params=None, timeout=20.0):
        return await client.get(url, params=params)

    for _name, _fn in (("get_json", fake_get_json),
                       ("get_text", fake_get_text),
                       ("request", fake_request)):
        if hasattr(module, _name):
            monkeypatch.setattr(module, _name, _fn)
    # raw-httpx modules (web.py reader stages) still resolve their own client
    if hasattr(module, "httpx"):
        monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kw: client)
    return client


PAPER = {"title": "Paper X", "doi": "https://doi.org/10.1/x",
         "id": "https://openalex.org/W5", "publication_date": "2026-01-01",
         "publication_year": 2026, "authorships": [], "primary_location": {},
         "open_access": {}, "cited_by_count": 1, "abstract_inverted_index": None}


def test_normalize_identifier():
    assert _normalize_identifier("arXiv:2603.1") == ("arxiv", "2603.1")
    assert _normalize_identifier("10.48550/arxiv.2603.1") == ("arxiv", "2603.1")
    assert _normalize_identifier("10.1/x") == ("doi", "10.1/x")
    assert _normalize_identifier("https://doi.org/10.1/y") == ("doi", "10.1/y")
    assert _normalize_identifier("2603.12345") == ("arxiv", "2603.12345")
    assert _normalize_identifier("random text") == ("other", "random text")


def test_pick_fields():
    d = {"title": "T", "url": "U", "snippet": "S", "published": "2026-01-01",
         "meta": {"doi": "10.1/x", "authors": ["A"], "year": 2026, "is_oa": True,
                  "citation_count": 3, "venue": "V", "arxiv_id": "1", "pdf_url": "P",
                  "abstract": "Abs", "paper_id": "W1", "publisher": "Pub",
                  "unknown": 1}}
    out = _pick_fields(d)
    assert out["doi"] == "10.1/x"
    assert out["citation_count"] == 3
    assert "unknown" not in out
    assert _pick_fields("not a dict") == {}


def test_get_paper_doi(monkeypatch):
    import kortex_search.sources.crossref as cr
    import kortex_search.sources.openalex as oa
    _mock_http(monkeypatch, oa, [FakeResp(PAPER)])
    _mock_http(monkeypatch, cr, [FakeResp({"message": {
        "title": ["Paper X"], "URL": "https://doi.org/10.1/x", "DOI": "10.1/x"}})])

    async def run():
        out = await get_paper("10.1/x")
        assert out["kind"] == "doi"
        assert out["title"] == "Paper X"

    asyncio.run(run())


def test_get_paper_arxiv(monkeypatch):
    import kortex_search.sources.arxiv as arx
    import kortex_search.sources.openalex as oa

    async def fake_get_text(url, **kw):
        return "<feed/>"

    _mock_http(monkeypatch, oa, [FakeResp(PAPER)])
    monkeypatch.setattr(arx, "get_text", fake_get_text)

    async def run():
        out = await get_paper("2603.12345")
        assert out["kind"] == "arxiv"

    asyncio.run(run())


def test_get_paper_title_search(monkeypatch):
    import kortex_search.sources.openalex as oa
    _mock_http(monkeypatch, oa, [FakeResp({"results": [PAPER]})])

    async def run():
        out = await get_paper("Paper X title")
        assert out["kind"] == "other"
        assert out.get("title") == "Paper X"

    asyncio.run(run())


def test_get_paper_source_error_is_caught(monkeypatch):

    async def boom(identifier):
        raise SourceError("openalex get failed: simulated")

    async def ok_crossref(identifier):
        return Result(title="Paper X", url="https://doi.org/10.1/x",
                      source="crossref")

    monkeypatch.setattr(ALL_SOURCES["openalex"], "get", boom)
    monkeypatch.setattr(ALL_SOURCES["crossref"], "get", ok_crossref)

    async def run():
        out = await get_paper("10.1/x")
        assert "error" in out.get("openalex", {})

    asyncio.run(run())


def test_get_citations_fallback(monkeypatch):

    async def fake_oa_citations(identifier, limit=20):
        return [Result(title="Paper X", url="https://doi.org/10.1/x",
                       source="openalex", published="2026-01-01")]

    async def fake_ss_citations(identifier, limit=20):
        raise AssertionError("openalex succeeded; fallback must not run")

    monkeypatch.setattr(ALL_SOURCES["openalex"], "citations", fake_oa_citations)
    monkeypatch.setattr(ALL_SOURCES["semantic_scholar"], "citations",
                        fake_ss_citations)

    async def run():
        out = await get_citations("10.1/x")
        assert out["engine"] == "openalex"
        assert out["count"] == 1
        assert out["results"][0]["title"] == "Paper X"

    asyncio.run(run())


def test_get_references_doi_and_unknown(monkeypatch):
    import kortex_search.sources.crossref as cr
    _mock_http(monkeypatch, cr, [FakeResp({"message": {"reference": [
        {"DOI": "10.9/r1", "article-title": "Ref1"},
    ]}})])

    async def run():
        out = await get_references("10.1/x")
        assert out["engine"] == "crossref"
        out2 = await get_references("not-an-id")
        assert out2["error"] == "unrecognized identifier"

    asyncio.run(run())


def test_research_answer_no_results(monkeypatch):
    from kortex_search import server

    async def fake_search(query, sources=None, **kw):
        return {"query": query, "count": 0, "results": [], "sources": {}}

    monkeypatch.setattr(server.orchestrator, "search", fake_search)

    async def run():
        out = await server.research_answer("nothing matches")
        assert out["answer"].startswith("No results")

    asyncio.run(run())


def test_saved_queries_actions(rds, monkeypatch):
    async def fake_search(query, sources=None, **kw):
        return {"query": query, "count": 1, "results": [
            {"title": "hit", "url": "https://h.com/", "source": "searxng"}]}

    monkeypatch.setattr(sq.orchestrator, "search", fake_search)

    async def run():
        assert sq.save("q1", "some query")["saved"] == "q1"
        assert sq.save("", "")["error"]
        listed = sq.list_all()
        assert any(r["name"] == "q1" for r in listed)
        r = await sq.run("q1", limit=5)
        assert r["count"] == 1
        d = await sq.diff("q1", limit=5)
        assert d["new"] == [] and d["unchanged"] == 1
        assert sq.delete("q1")["deleted"] is True
        assert sq.delete("q1")["deleted"] is False
        assert (await sq.run("nope"))["error"]
        assert (await sq.diff("nope"))["error"]

    asyncio.run(run())


def test_expand_query_uses_llm_variants(monkeypatch):
    from kortex_search import orchestrator as orch

    async def fake_complete(messages, **kw):
        return "alternative phrasing one\n- second alternative query here"

    monkeypatch.setattr(orch, "QUERY_EXPANSION", True)
    monkeypatch.setattr(orch.llm, "available", lambda: True)
    monkeypatch.setattr(orch.llm, "complete", fake_complete)

    async def run():
        variants = await orch._expand_query("original query")
        assert variants == ["alternative phrasing one", "second alternative query here"]

    asyncio.run(run())


def test_expand_query_disabled_or_fails(monkeypatch):
    from kortex_search import orchestrator as orch
    monkeypatch.setattr(orch, "QUERY_EXPANSION", False)

    async def run():
        assert await orch._expand_query("x") == []
        monkeypatch.setattr(orch, "QUERY_EXPANSION", True)
        monkeypatch.setattr(orch.llm, "available", lambda: True)

        async def boom(messages, **kw):
            raise RuntimeError("llm down")

        monkeypatch.setattr(orch.llm, "complete", boom)
        assert await orch._expand_query("x") == []

    asyncio.run(run())


def test_diversity_domain_edge():
    from kortex_search.diversity import _domain
    assert _domain("https://www.worldwide.com/x") == "worldwide.com"
    assert _domain("") == ""
    assert _domain("not a url") == ""


def test_fusion_unweighted():
    from kortex_search.fusion import rrf_fuse
    lists = [[Result(title="a", url="https://a.com/1", source="s1")]]
    fused = rrf_fuse(lists, weighted=False)
    assert len(fused) == 1 and fused[0].meta["score_raw"] > 0


def test_rerank_disabled_passthrough(monkeypatch):
    from kortex_search import rerank
    monkeypatch.setattr(rerank, "SEMANTIC_RERANK", False)
    res = [Result(title="a", url="https://a.com/1")]
    out = rerank.rerank("q", res, top_k=1)
    assert out == res


def test_rerank_model_missing_passthrough(monkeypatch):
    from kortex_search import rerank
    monkeypatch.setattr(rerank, "SEMANTIC_RERANK", True)
    monkeypatch.setattr(rerank, "_model", None)
    monkeypatch.setattr(rerank, "_model_error", "load failed")
    res = [Result(title="a", url="https://a.com/1")]
    assert rerank.rerank("q", res) == res


def test_cli_version_and_check(monkeypatch):
    from kortex_search.cli import _cmd_check, _cmd_version

    class A:
        pass

    assert _cmd_version(A()) == 0

    import kortex_search.health as health
    async def fake_check():
        return (True, {"sources": 18, "redis": {"ok": True},
                       "llm": {"available": True}})

    monkeypatch.setattr(health, "check", fake_check)
    assert _cmd_check(A()) == 0


# --------------------------------------------------------------------------
# Grounded research_answer (sweep 2026-09-01): JSON synthesis + deterministic
# citation verification
# --------------------------------------------------------------------------

class TestGroundedAnswer:
    GOOD = (json.dumps({
        "answer_md": "PostgreSQL VACUUM reclaims dead tuples [1] and updates "
                     "statistics [2].",
        "citations": [
            {"id": 1, "quote": "VACUUM reclaims storage occupied by dead tuples"},
            {"id": 2, "quote": "VACUUM updates statistics"},
        ],
        "insufficient_evidence": False,
    }))

    def _run(self, monkeypatch, raw, snippets=("VACUUM reclaims storage "
              "occupied by dead tuples", "VACUUM updates statistics")):
        from kortex_search import server

        async def fake_search(query, sources=None, **kw):
            return {"query": query, "count": 2, "results": [
                {"title": "Postgres docs", "url": "https://p.org/vacuum",
                 "snippet": snippets[0], "source": "web"},
                {"title": "Wiki", "url": "https://w.org/vacuum",
                 "snippet": snippets[1], "source": "wikipedia"},
            ], "sources": {}}

        async def fake_complete(messages, **kw):
            assert kw.get("json_mode") is True
            return raw

        monkeypatch.setattr(server.orchestrator, "search", fake_search)
        monkeypatch.setattr(server.llm, "complete", fake_complete)
        return asyncio.run(server.research_answer("vacuum?"))

    def test_grounded_answer_verified(self, monkeypatch):
        out = self._run(monkeypatch, self.GOOD)
        assert out["answer"] == ("PostgreSQL VACUUM reclaims dead tuples [1] "
                                 "and updates statistics [2].")
        assert [c["n"] for c in out["citations"]] == [1, 2]
        assert out["citations"][0]["quote"].startswith("VACUUM reclaims")
        assert out["insufficient_evidence"] is False
        assert out["verification"]["status"] == "verified"
        assert out["verification"]["hallucinated_ids"] == []

    def test_hallucinated_marker_dropped(self, monkeypatch):
        out = self._run(monkeypatch, json.dumps({
            "answer_md": "Claim with a real cite [1] and a fake one [9].",
            "citations": [{"id": 1, "quote": "VACUUM reclaims storage occupied "
                                             "by dead tuples"}],
            "insufficient_evidence": False,
        }))
        assert "[9]" not in out["answer"]
        assert "[1]" in out["answer"]
        assert out["verification"]["hallucinated_ids"] == ["9"]

    def test_quote_mismatch_drops_citation(self, monkeypatch):
        out = self._run(monkeypatch, json.dumps({
            "answer_md": "Claim [1] and another [2].",
            "citations": [
                {"id": 1, "quote": "VACUUM reclaims storage occupied by dead tuples"},
                {"id": 2, "quote": "THIS TEXT IS NOT IN ANY SOURCE"},
            ],
            "insufficient_evidence": False,
        }))
        assert [c["n"] for c in out["citations"]] == [1]
        assert "[2]" not in out["answer"]
        assert out["verification"]["dropped_unverifiable"] == 1

    def test_json_degradation_is_honest(self, monkeypatch):
        out = self._run(monkeypatch, "plain text answer, no json at all")
        assert out["answer"] == "plain text answer, no json at all"
        assert out["verification"]["status"] == "unverified-json-degraded"

    def test_json_wrapped_in_noise_still_parses(self, monkeypatch):
        out = self._run(monkeypatch, "```json\n" + self.GOOD + "\n```")
        assert out["verification"]["status"] == "verified"

    def test_synthesis_failure_reports(self, monkeypatch):
        from kortex_search import server

        async def fake_search(query, sources=None, **kw):
            return {"query": query, "count": 1, "results": [
                {"title": "x", "url": "https://x.com/", "snippet": "s",
                 "source": "web"}], "sources": {}}

        async def boom(messages, **kw):
            raise RuntimeError("deepseek down")

        monkeypatch.setattr(server.orchestrator, "search", fake_search)
        monkeypatch.setattr(server.llm, "complete", boom)
        out = asyncio.run(server.research_answer("q"))
        assert out["answer"].startswith("(answer synthesis failed:")
