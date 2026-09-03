"""Parser tests for all 18 source adapters — hermetic, no network.

HTTP sources: monkeypatched httpx.AsyncClient with canned responses.
CLI sources: monkeypatched run_cmd/run_opencli with canned stdout.
Every parser's happy path + error path is exercised.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from kortex_search.sources import ALL_SOURCES
from kortex_search.sources.base import SourceError


class FakeResp:
    def __init__(self, payload=None, text="", status_code=200):
        self._payload = payload
        self._text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPError(f"http {self.status_code}")

    def json(self):
        return self._payload

    @property
    def text(self):
        return self._text

    @property
    def headers(self):
        return {}


class FakeClient:
    """httpx.AsyncClient drop-in: returns a scripted response per call."""

    def __init__(self, responses=None, **kwargs):
        self.responses = list(responses or [])
        self.calls = []
        self._last = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def _next(self):
        if self.responses:
            self._last = self.responses.pop(0)
        if self._last is not None:
            return self._last
        return FakeResp({})

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return await self._next()

    async def request(self, method, url, **kwargs):
        # extract.http uses client.request(); route to the scripted queue.
        self.calls.append((url, kwargs))
        return await self._next()


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
    # raw-httpx modules (web.py reader stages) resolve their own shared pool
    # (sweep 2026-08-31) — drop the cached singleton so the re-patched
    # AsyncClient takes effect on every _mock_http call
    if hasattr(module, "httpx"):
        monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kw: client)
    for _pool in ("_scrape", "_scrape_sync"):
        if hasattr(module, _pool):
            monkeypatch.setattr(module, _pool, None)
    return client


def _mock_cmd(monkeypatch, module, code=0, out=""):
    async def fake_run_cmd(cmd, **kwargs):
        return code, out

    async def fake_run_opencli(cmd, **kwargs):
        return code, out

    if hasattr(module, "run_cmd"):
        monkeypatch.setattr(module, "run_cmd", fake_run_cmd)
    if hasattr(module, "run_opencli"):
        monkeypatch.setattr(module, "run_opencli", fake_run_opencli)

def _r(src_name):
    return ALL_SOURCES[src_name]


# --------------------------------------------------------------------------
# HTTP sources
# --------------------------------------------------------------------------

def test_searxng_parses_results(monkeypatch):
    import kortex_search.sources.searxng as mod
    _mock_http(monkeypatch, mod, [FakeResp({"results": [
        {"title": "Alpha Go", "url": "https://a.com/", "content": "snippet",
         "engine": "google", "publishedDate": "2026-08-20", "category": "general",
         "engines": ["google"]},
        {"title": "Beta", "url": "https://b.com/", "content": "s2"},
    ]})])

    async def run():
        return await _r("searxng").search("go", limit=10, category="news", freshness="week")

    out = asyncio.run(run())
    assert len(out) == 2
    assert out[0].title == "Alpha Go" and out[0].published == "2026-08-20"
    assert out[0].meta["engines"] == ["google"]


def test_searxng_error_raises(monkeypatch):
    import kortex_search.sources.searxng as mod
    _mock_http(monkeypatch, mod, [FakeResp({}, status_code=500)])

    async def run():
        with pytest.raises(SourceError, match="searxng"):
            await _r("searxng").search("x")
    asyncio.run(run())


def test_github_parses_and_rate_limit(monkeypatch):
    import kortex_search.sources.github as mod
    _mock_http(monkeypatch, mod, [FakeResp({"items": [
        {"full_name": "kbj/Aionos", "html_url": "https://github.com/kbj/Aionos",
         "description": "astrology engine", "created_at": "2026-01-01T00:00:00Z",
         "stargazers_count": 42, "language": "Rust", "forks_count": 7},
    ]})])

    async def run():
        out = await _r("github").search("aionos")
        assert out[0].title == "kbj/Aionos"
        assert out[0].meta["stars"] == 42
        # 403 → explicit rate-limit error
        _mock_http(monkeypatch, mod, [FakeResp({}, status_code=403)])
        with pytest.raises(SourceError, match="rate-limited"):
            await _r("github").search("x")

    asyncio.run(run())


def test_v2ex_parses_and_normalizes_epoch(monkeypatch):
    import kortex_search.sources.v2ex as mod
    _mock_http(monkeypatch, mod, [FakeResp({"hits": [
        {"_source": {"id": 123, "title": "Rust 异步编程", "content": "正文",
                     "created": 1774000000, "member": "k", "replies": 5}},
    ]})])

    async def run():
        out = await _r("v2ex").search("rust 异步")
        assert out[0].url == "https://www.v2ex.com/t/123"
        assert out[0].published is not None and out[0].published.startswith("2026-")
        assert out[0].meta["replies"] == 5

    asyncio.run(run())


ARXIV_XML = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <title>Deterministic Ephemeris Computation</title>
    <id>http://arxiv.org/abs/2603.12345v1</id>
    <summary>A precise method for planetary positions.</summary>
    <published>2026-03-15T00:00:00Z</published>
    <arxiv:doi>10.48550/arXiv.2603.12345</arxiv:doi>
    <author><name>K. Author</name></author>
    <arxiv:primary_category term="astro-ph"/>
    <link title="pdf" href="http://arxiv.org/pdf/2603.12345"/>
  </entry>
  <entry>
    <title>Second Paper</title>
    <id>http://arxiv.org/abs/2604.99999v2</id>
    <summary>Another abstract.</summary>
    <published>2026-04-01T00:00:00Z</published>
  </entry>
</feed>"""


def test_arxiv_search_and_parse(monkeypatch):
    import kortex_search.sources.arxiv as mod
    _mock_http(monkeypatch, mod, [FakeResp(text=ARXIV_XML)])

    async def run():
        out = await _r("arxiv").search("ephemeris", limit=5)
        assert len(out) == 2
        r = out[0]
        assert r.meta["arxiv_id"] == "2603.12345v1"
        assert r.meta["authors"] == ["K. Author"]
        assert r.meta["is_oa"] is True
        assert r.meta["pdf_url"] == "http://arxiv.org/pdf/2603.12345"
        assert r.published == "2026-03-15T00:00:00Z"
        # get() by id
        _mock_http(monkeypatch, mod, [FakeResp(text=ARXIV_XML)])
        got = await _r("arxiv").get("2603.12345")
        assert got.title.startswith("Deterministic")
        # no results → error
        _mock_http(monkeypatch, mod, [FakeResp(text="<feed/>")])
        with pytest.raises(SourceError, match="no paper"):
            await _r("arxiv").get("9999.99999")

    asyncio.run(run())


def test_arxiv_malformed_xml(monkeypatch):
    import kortex_search.sources.arxiv as mod
    _mock_http(monkeypatch, mod, [FakeResp(text="<not-xml")])

    async def run():
        with pytest.raises(SourceError, match="arxiv"):
            await _r("arxiv").search("x")

    asyncio.run(run())


def test_bilibili_parses_blocks(monkeypatch):

    import kortex_search.sources.bilibili as mod
    monkeypatch.setattr(mod, "BILIBILI_WBI", False)  # parser test, not signing
    payload = {"code": 0, "data": {"result": [
        {"result_type": "video", "data": [
            {"title": '<em class="keyword">异步</em>编程', "arcurl": "https://b23.tv/1",
             "description": "desc", "author": "up主", "play": 100},
            "garbage-string-item",
        ]},
        {"result_type": "bili_user", "data": [
            {"title": "某人", "url": "https://space.bilibili.com/2", "description": "x"},
        ]},
    ]}}
    _mock_http(monkeypatch, mod, [FakeResp(payload)])

    async def run():
        out = await _r("bilibili").search("异步")
        assert len(out) == 2
        assert out[0].title == "异步编程"  # em tags stripped
        assert out[0].meta["play"] == 100
        assert out[1].meta["type"] == "bili_user"

    asyncio.run(run())


def test_bilibili_api_error(monkeypatch):
    import kortex_search.sources.bilibili as mod
    monkeypatch.setattr(mod, "BILIBILI_WBI", False)
    _mock_http(monkeypatch, mod,
               [FakeResp({"code": -412, "message": "risk control"})])

    async def run():
        with pytest.raises(SourceError, match="risk control"):
            await _r("bilibili").search("x")

    asyncio.run(run())

def test_openalex_search_filters(monkeypatch):
    import kortex_search.sources.openalex as mod
    _mock_http(monkeypatch, mod, [FakeResp({"results": [
        {"title": "Graph Fusion", "id": "https://openalex.org/W9",
         "doi": "https://doi.org/10.1/9", "publication_date": "2026-05-01",
         "publication_year": 2026, "authorships": [{"author": {"display_name": "A"}}],
         "primary_location": {"landing_page_url": "https://journal.example/",
                              "source": {"display_name": "JML"}},
         "open_access": {"is_oa": True, "oa_url": "https://pdf.example/"},
         "cited_by_count": 3, "abstract_inverted_index": None},
    ]})])

    async def run():
        out = await _r("openalex").search("fusion", limit=5, year_from=2025, open_access_only=True)
        assert out[0].meta["doi"] == "10.1/9"
        assert out[0].meta["authors"] == ["A"]
        assert out[0].meta["venue"] == "JML"
        assert out[0].published == "2026-05-01"

    asyncio.run(run())


def test_crossref_year_published_normalized(monkeypatch):
    import kortex_search.sources.crossref as mod
    _mock_http(monkeypatch, mod, [FakeResp({"message": {"items": [
        {"title": ["Fusion Survey"], "URL": "https://doi.org/10.2/x",
         "abstract": "<jats:p>Abstract text</jats:p>",
         "issued": {"date-parts": [[2026, 1, 15]]},
         "DOI": "10.2/x", "author": [{"family": "B", "given": "C"}],
         "container-title": ["JML"]},
    ]}})])

    async def run():
        out = await _r("crossref").search("fusion")
        assert out[0].published == "2026-01-01"  # year-only normalized
        assert out[0].meta["doi"] == "10.2/x"

    asyncio.run(run())


def test_semantic_scholar_year_published_normalized(monkeypatch):
    import kortex_search.sources.semantic_scholar as mod
    _mock_http(monkeypatch, mod, [FakeResp({"data": [
        {"title": "S2 Paper", "url": "https://s2.example/1", "abstract": "abs",
         "year": 2026, "paperId": "p1",
         "externalIds": {"DOI": "10.3/y", "ArXiv": "2601.1"},
         "authors": [{"name": "D"}], "openAccessPdf": {"url": "https://pdf.s2/1"}},
    ]})])

    async def run():
        out = await _r("semantic_scholar").search("s2")
        assert out[0].published == "2026-01-01"
        assert out[0].meta["arxiv_id"] == "2601.1"
        # citations shape
        _mock_http(monkeypatch, mod, [FakeResp({"data": [
            {"citingPaper": {"title": "Citing Work", "year": 2025,
                             "externalIds": {}, "authors": []}},
        ]})])
        cites = await _r("semantic_scholar").citations("10.3/y")
        assert cites[0].title == "Citing Work"
        # 429 → retries then SourceError
        _mock_http(monkeypatch, mod, [FakeResp({}, status_code=429)])
        with pytest.raises(SourceError, match="429"):
            await _r("semantic_scholar").search("x")
        mod._until = 0.0  # clear the process-wide cooldown for later tests

    asyncio.run(run())


def test_semantic_scholar_429_fast_fails_with_cooldown(monkeypatch):
    """A 429 must fail FAST (single request, no retry burn) and set the
    process-wide cooldown; subsequent calls raise without any HTTP request
    (sweep 2026-09-03: the old retry-then-fail burned ~12s per call)."""
    import time

    import kortex_search.sources.semantic_scholar as mod

    monkeypatch.setattr(mod, "_until", 0.0)
    _mock_http(monkeypatch, mod, [FakeResp({}, status_code=429)])
    calls: list[str] = []
    orig_request = mod.request

    async def counting_request(method, url, **kw):
        calls.append(url)
        return await orig_request(method, url, **kw)

    monkeypatch.setattr(mod, "request", counting_request)

    async def run():
        t0 = time.monotonic()
        with pytest.raises(SourceError, match="cooldown set"):
            await _r("semantic_scholar").search("x")
        assert time.monotonic() - t0 < 2.0, "429 must fail fast, not retry"
        assert mod.rate_limited_until() > time.monotonic()
        assert len(calls) == 1, "429 must not retry"
        # cooldown active → raise without touching the network
        with pytest.raises(SourceError, match="cooldown active"):
            await _r("semantic_scholar").search("y")
        assert len(calls) == 1, "cooldown-gated call must not hit the network"
        mod._until = 0.0

    asyncio.run(run())


def test_stackoverflow_parses_epoch(monkeypatch):
    import kortex_search.sources.stackoverflow as mod
    _mock_http(monkeypatch, mod, [FakeResp({"items": [
        {"title": "How to fuse?", "link": "https://so.com/q/1",
         "body": "<p>body</p>", "creation_date": 1760000000,
         "question_id": 1, "accepted_answer_id": 99, "answer_count": 4,
         "is_answered": True, "owner": {"display_name": "so-user"},
         "score": 5, "view_count": 100, "tags": ["search"]},
    ]})])

    async def run():
        out = await _r("stackoverflow").search("fuse")
        r = out[0]
        assert r.snippet.strip() == "body"  # HTML stripped
        assert r.published is not None and r.published.startswith("2025-")
        assert r.meta["accepted"] is True
        assert r.meta["author"] == "so-user"

    asyncio.run(run())


def test_web_read_and_search(monkeypatch):
    import kortex_search.sources.web as mod
    _mock_http(monkeypatch, mod, [FakeResp(text="x" * 30000)])

    async def run():
        text = await _r("web").read("https://example.com/")
        assert len(text) == 20000  # capped
        assert await _r("web").search("anything") == []  # reader, not searcher
        _mock_http(monkeypatch, mod, [FakeResp({}, status_code=404)])
        with pytest.raises(SourceError, match="jina"):
            await _r("web").read("https://example.com/nope")

    asyncio.run(run())


# --------------------------------------------------------------------------
# CLI sources
# --------------------------------------------------------------------------

def test_youtube_parses_json_lines(monkeypatch):
    import kortex_search.sources.youtube as mod
    payload = "\n".join([
        json.dumps({"title": "V1", "webpage_url": "https://youtu.be/1",
                    "description": "d1", "upload_date": "20260820",
                    "uploader": "ch", "duration": 300, "view_count": 10}),
        "not-json-garbage",
        json.dumps({"title": "V2", "url": "https://youtu.be/2"}),
    ])
    _mock_cmd(monkeypatch, mod, code=0, out=payload)

    async def run():
        out = await _r("youtube").search("cats", limit=5)
        assert len(out) == 2
        assert out[0].published == "20260820"
        assert out[0].meta["views"] == 10
        # nonzero exit → SourceError
        _mock_cmd(monkeypatch, mod, code=1, out="yt-dlp error")
        with pytest.raises(SourceError, match="yt-dlp"):
            await _r("youtube").search("x")

    asyncio.run(run())


def test_exa_parses_blocks(monkeypatch):
    import kortex_search.sources.exa as mod
    payload = "\n---\nTitle: Neural Search\nURL: https://exa.example/1\n" \
              "Published: 2026-08-01T00:00:00.000Z\nAuthor: A\nHighlights: hl\n" \
              "\n---\nTitle: Only URL\nURL: https://exa.example/2\n" \
              "\n---\nPublished: N/A\n"
    _mock_cmd(monkeypatch, mod, code=0, out=payload)

    async def run():
        out = await _r("exa").search("neural", limit=5)
        assert len(out) == 2
        assert out[0].title == "Neural Search"
        assert out[0].published == "2026-08-01T00:00:00.000Z"
        assert out[1].title == "Only URL"
        _mock_cmd(monkeypatch, mod, code=2, out="mcporter error")
        with pytest.raises(SourceError, match="exa"):
            await _r("exa").search("x")

    asyncio.run(run())


TWITTER_CLI_JSON = json.dumps({"ok": True, "data": [
    {"text": "First tweet", "id": "1", "author": "kai",
     "url": "https://x.com/kai/status/1", "created_at": "2026-08-20T10:00:00.000Z",
     "likes": 3, "views": 50},
]})


def test_twitter_backend1_success(monkeypatch, tmp_path):
    import kortex_search.sources.twitter as mod
    from kortex_search.extract import vault as vault_mod
    envfile = tmp_path / "twitter.env"
    envfile.write_text('TWITTER_AUTH_TOKEN="t"\nTWITTER_CT0="c"\n')
    monkeypatch.setitem(vault_mod._CONFIG_PATHS, "twitter", str(envfile))
    monkeypatch.setitem(vault_mod.LEGACY_PATHS, "twitter", str(tmp_path / "nope.env"))

    async def fake_run_cmd(cmd, **kwargs):
        return 0, TWITTER_CLI_JSON

    monkeypatch.setattr(mod, "run_cmd", fake_run_cmd)

    async def run():
        out = await _r("twitter").search("opencode", limit=5)
        assert out[0].title.startswith("First tweet")
        assert out[0].meta["author"] == "kai"
        assert out[0].engine == "twitter-cli"

    asyncio.run(run())


def test_twitter_backend2_opencli_fallback(monkeypatch):
    import kortex_search.sources.twitter as mod
    from kortex_search.extract import vault as vault_mod
    monkeypatch.setitem(vault_mod._CONFIG_PATHS, "twitter", "/nonexistent.env")
    monkeypatch.setitem(vault_mod.LEGACY_PATHS, "twitter", "/nonexistent.env")  # no auth

    async def fake_run_cmd(cmd, **kwargs):
        return 0, "{}"  # backend1 empty

    async def fake_run_opencli(cmd, **kwargs):
        return 0, json.dumps([{"text": "opencli tweet", "id": "9", "author": "kai"}])

    monkeypatch.setattr(mod, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(mod, "run_opencli", fake_run_opencli)

    async def run():
        out = await _r("twitter").search("opencode", limit=5)
        assert out[0].engine == "opencli"
        assert out[0].meta["author"] == "kai"

    asyncio.run(run())


def test_twitter_both_backends_fail(monkeypatch):
    import kortex_search.sources.twitter as mod
    from kortex_search.extract import vault as vault_mod
    monkeypatch.setitem(vault_mod._CONFIG_PATHS, "twitter", "/nonexistent.env")
    monkeypatch.setitem(vault_mod.LEGACY_PATHS, "twitter", "/nonexistent.env")

    async def fake_run_cmd(cmd, **kwargs):
        return 1, "fail"

    async def fake_run_opencli(cmd, **kwargs):
        return 1, "fail"

    monkeypatch.setattr(mod, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(mod, "run_opencli", fake_run_opencli)

    async def run():
        with pytest.raises(SourceError, match="failed"):
            await _r("twitter").search("x")

    asyncio.run(run())


def test_reddit_parses_list_and_dict(monkeypatch):
    import kortex_search.sources.reddit as mod
    _mock_cmd(monkeypatch, mod, code=0, out=json.dumps([
        {"title": "R post", "url": "https://reddit.com/r/x/1", "selftext": "body",
         "subreddit": "x", "author": "u", "score": 9, "comments": 2},
    ]))

    async def run():
        out = await _r("reddit").search("rust", limit=5)
        assert out[0].meta["subreddit"] == "x"
        assert out[0].meta["engagement"]["comments"] == 2
        # dict-wrapped results
        _mock_cmd(monkeypatch, mod, code=0, out=json.dumps({"data": [
            {"title": "dict post", "url": "https://reddit.com/r/x/2", "selftext": ""},
        ]}))
        out2 = await _r("reddit").search("rust")
        assert out2[0].title == "dict post"
        # error
        _mock_cmd(monkeypatch, mod, code=1, out="opencli error")
        with pytest.raises(SourceError, match="reddit"):
            await _r("reddit").search("x")

    asyncio.run(run())


def test_facebook_instagram_xiaohongshu_parse(monkeypatch):
    import kortex_search.sources.facebook as fb
    import kortex_search.sources.instagram as ig
    import kortex_search.sources.xiaohongshu as xhs

    async def run():
        # facebook
        _mock_cmd(monkeypatch, fb, code=0, out=json.dumps(
            [{"title": "FB post", "url": "https://fb.com/1", "text": "t"}]))
        out = await _r("facebook").search("x")
        assert out[0].title == "FB post"
        _mock_cmd(monkeypatch, fb, code=1, out="err")
        with pytest.raises(SourceError, match="facebook"):
            await _r("facebook").search("x")

        # instagram
        _mock_cmd(monkeypatch, ig, code=0, out=json.dumps(
            [{"name": "Kaiser", "username": "kaichen", "url": "https://ig.com/1",
              "verified": True}]))
        out = await _r("instagram").search("kai")
        assert out[0].title == "Kaiser"
        assert out[0].url == "https://ig.com/1"
        assert out[0].meta["verified"] is True

        # xiaohongshu
        _mock_cmd(monkeypatch, xhs, code=0, out=json.dumps(
            [{"title": "XHS post", "url": "https://xhslink.com/1", "desc": "d",
              "author": "creator"}]))
        out = await _r("xiaohongshu").search("笔记")
        assert out[0].title == "XHS post"
        assert out[0].meta["author"] == "creator"
        _mock_cmd(monkeypatch, xhs, code=1, out="not configured")
        with pytest.raises(SourceError, match="xiaohongshu"):
            await _r("xiaohongshu").search("x")

    asyncio.run(run())


def test_linkedin_parses_text_blocks(monkeypatch):
    import kortex_search.sources.linkedin as mod
    payload = (
        "Name: Ada Lovelace\n"
        "Headline: Engineer\n"
        "URL: https://linkedin.com/in/ada\n"
        "---\n"
        "Name: Grace Hopper\n"
        "Current Position: Admiral\n"
        "Profile URL: https://linkedin.com/in/grace\n"
    )
    _mock_cmd(monkeypatch, mod, code=0, out=payload)

    async def run():
        out = await _r("linkedin").search("pioneers", limit=5)
        assert len(out) == 2
        assert out[0].title == "Ada Lovelace"
        assert out[0].url == "https://linkedin.com/in/ada"
        assert out[1].snippet == "Admiral"
        _mock_cmd(monkeypatch, mod, code=1, out="no session")
        with pytest.raises(SourceError, match="linkedin"):
            await _r("linkedin").search("x")

    asyncio.run(run())


# --------------------------------------------------------------------------
# guard_query applies at the source layer (B3/M5)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cli_sources_reject_leading_dash(monkeypatch):
    import kortex_search.sources.reddit as rd
    import kortex_search.sources.youtube as yt

    async def fake_run_cmd(cmd, **kwargs):
        raise AssertionError("must not reach the CLI")

    async def fake_run_opencli(cmd, **kwargs):
        raise AssertionError("must not reach the CLI")

    monkeypatch.setattr(yt, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(rd, "run_opencli", fake_run_opencli)

    with pytest.raises(SourceError, match="flag-injection"):
        await yt.YouTubeSource().search("-l user")
    with pytest.raises(SourceError, match="flag-injection"):
        await rd.RedditSource().search("-l user")


# --- CN tier (v0.4): zhihu / weibo / baidu / toutiao -------------------------

_ZHIHU_PAYLOAD = {
    "data": [
        {"object": {"type": "answer", "id": 9001, "question": {
            "id": 123, "name": "<em>异步</em>编程怎么做?"},
            "excerpt": "<p>先学事件循环</p>", "voteup_count": 42,
            "comment_count": 3, "author": {"name": "某乎友"},
            "created_time": 1700000000}},
        {"object": {"type": "article", "id": 777, "title": "RAG 综述",
                    "url": "https://zhuanlan.zhihu.com/p/777",
                    "excerpt": "检索增强生成", "author": {"name": "A"},
                    "created": 1700000001}},
        {"object": {"type": "question", "id": 555, "title": "如何学习 Rust?",
                    "excerpt": "求路线", "answer_count": 9}},
        {"object": {"type": "zvideo", "id": 1, "title": "忽略我"}},
    ]
}


@pytest.mark.asyncio
async def test_zhihu_parses_answer_article_question(monkeypatch):

    import kortex_search.sources.zhihu as zh
    monkeypatch.setattr(zh, "CN_SOURCES", True)
    monkeypatch.setattr(zh, "ZHIHU_COOKIE", "d_c0=abc; z_c0=def")
    _mock_http(monkeypatch, zh, [FakeResp(_ZHIHU_PAYLOAD)])

    out = await zh.ZhihuSource().search("异步")
    assert len(out) == 3  # zvideo filtered
    answer, article, question = out
    assert answer.title == "异步编程怎么做?"  # html stripped
    assert answer.url == "https://www.zhihu.com/question/123/answer/9001"
    assert answer.meta["zhihu_type"] == "answer"
    assert answer.meta["voteup_count"] == 42
    assert answer.meta["author"] == "某乎友"
    assert article.meta["zhihu_type"] == "article"
    assert question.meta["answer_count"] == 9


@pytest.mark.asyncio
async def test_zhihu_requires_cookie(monkeypatch):
    import kortex_search.sources.zhihu as zh
    monkeypatch.setattr(zh, "CN_SOURCES", True)
    monkeypatch.setattr(zh, "ZHIHU_COOKIE", "")
    with pytest.raises(SourceError, match="auth:"):
        await zh.ZhihuSource().search("x")


@pytest.mark.asyncio
async def test_zhihu_disabled_without_flag(monkeypatch):
    import kortex_search.sources.zhihu as zh
    monkeypatch.setattr(zh, "CN_SOURCES", False)
    with pytest.raises(SourceError, match="disabled"):
        await zh.ZhihuSource().search("x")


_WEIBO_HOT = {"data": {"realtime": [
    {"word": "某品牌道歉", "rank": 1, "num": 2845013, "category": "社会",
     "is_new": True, "is_hot": True},
    {"word": "某球星退役", "rank": 2, "num": 999999, "category": "体育"},
], "hotgovs": [{"word": "官方政策解读", "rank": 100}]}}


@pytest.mark.asyncio
async def test_weibo_hot_list_fallback(monkeypatch):

    import kortex_search.sources.weibo as wb
    monkeypatch.setattr(wb, "CN_SOURCES", True)
    monkeypatch.setattr(wb, "WEIBO_SUB", "")  # no SUB → hot list
    _mock_http(monkeypatch, wb, [FakeResp(_WEIBO_HOT)])

    out = await wb.WeiboSource().search("")
    assert len(out) == 3
    assert out[0].title == "某品牌道歉"
    assert out[0].meta["rank"] == 1
    assert out[0].meta["heat"] == 2845013
    assert "s.weibo.com" in out[0].url
    # query filter narrows the hot list
    filtered = await wb.WeiboSource().search("球星")
    assert [r.title for r in filtered] == ["某球星退役"]


_WEIBO_SUB_SEARCH = {"data": {"cards": [
    {"card_group": [{"mblog": {"text": "今天<em>天气</em>不错",
                               "mid": "M1", "bid": "B1",
                               "user": {"screen_name": "博主"},
                               "reposts_count": 5, "comments_count": 2,
                               "attitudes_count": 9,
                               "created_at": "2026-08-01"}}]},
]}}

@pytest.mark.asyncio
async def test_weibo_keyword_search_with_sub(monkeypatch):

    import kortex_search.sources.weibo as wb
    monkeypatch.setattr(wb, "CN_SOURCES", True)
    monkeypatch.setattr(wb, "WEIBO_SUB", "SUB=abc")
    _mock_http(monkeypatch, wb, [FakeResp(_WEIBO_SUB_SEARCH)])

    out = await wb.WeiboSource().search("天气")
    assert len(out) == 1
    assert out[0].title == "今天天气不错"  # em stripped
    assert out[0].url == "https://weibo.com/博主/B1"
    assert out[0].meta["likes"] == 9


_BAIDU_BOARD = {"data": {"cards": [
    {"word": "百度热搜第一", "hotScore": 12345, "index": 1,
     "category": "综合"},
    {"word": "另一个话题", "hotScore": 543, "index": 2, "url": "https://b"},
]}}

@pytest.mark.asyncio
async def test_baidu_board(monkeypatch):

    import kortex_search.sources.baidu as bd
    monkeypatch.setattr(bd, "CN_SOURCES", True)
    _mock_http(monkeypatch, bd, [FakeResp(_BAIDU_BOARD)])

    out = await bd.BaiduSource().search("")
    assert len(out) == 2
    assert out[0].title == "百度热搜第一"
    assert out[0].meta["heat"] == 12345
    assert "baidu.com" in out[0].url
    assert [r.title for r in await bd.BaiduSource().search("话题")] \
        == ["另一个话题"]


_TOUTIAO_BOARD = {"data": [
    {"Title": "头条热榜第一", "Url": "https://t/1", "HotValue": 888,
     "Label": "热", "Category": "科技", "Index": 1},
    {"Title": "普通新闻", "Url": "https://t/2", "HotValue": 100,
     "Label": "新", "Index": 2},
]}

@pytest.mark.asyncio
async def test_toutiao_board(monkeypatch):

    import kortex_search.sources.toutiao as tt
    monkeypatch.setattr(tt, "CN_SOURCES", True)
    _mock_http(monkeypatch, tt, [FakeResp(_TOUTIAO_BOARD)])

    out = await tt.ToutiaoSource().search("")
    assert len(out) == 2
    assert out[0].title == "头条热榜第一"
    assert out[0].meta["heat"] == 888
    assert out[0].meta["is_hot"] is True
    assert out[1].meta["is_new"] is True



# --------------------------------------------------------------------------
# Baidu board (0.4.3: dual-shape parser + drift guard, PHASE8 Plan 1)
# --------------------------------------------------------------------------

_BAIDU_LEGACY = {"data": {"cards": [
    {"word": "旧版热搜", "hotScore": 123456, "index": 1,
     "url": "https://www.baidu.com/s?wd=x", "is_hot": True},
    {"word": "旧版第二", "hotScore": 100, "index": 2},
]}}


def _baidu_fixture() -> dict:
    import json as _json
    from pathlib import Path
    return _json.loads(
        Path(__file__).parent.joinpath(
            "fixtures/platforms/baidu_board.json").read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_baidu_board_current_shape(monkeypatch):
    import kortex_search.sources.baidu as bd
    monkeypatch.setattr(bd, "CN_SOURCES", True)
    async def _fake(*_a, **_k):
        return _baidu_fixture()
    monkeypatch.setattr(bd, "get_json", _fake)
    out = await bd.BaiduSource().search("", limit=50)
    assert len(out) >= 30
    first = out[0]
    assert first.title and first.url.startswith("http")
    assert first.meta["rank"] >= 0
    assert "heat" in first.meta
    assert "pinned" in first.meta
    # query filtering works on the current shape
    top = out[0].title
    filtered = await bd.BaiduSource().search(top[:6])
    assert filtered and filtered[0].title == top


@pytest.mark.asyncio
async def test_baidu_board_legacy_shape(monkeypatch):
    import kortex_search.sources.baidu as bd
    monkeypatch.setattr(bd, "CN_SOURCES", True)
    async def _fake(*_a, **_k):
        return _BAIDU_LEGACY
    monkeypatch.setattr(bd, "get_json", _fake)
    out = await bd.BaiduSource().search("")
    assert len(out) == 2
    assert out[0].title == "旧版热搜"
    assert out[0].meta["heat"] == 123456
    assert out[0].meta["is_hot"] is True


@pytest.mark.asyncio
async def test_baidu_board_shape_drift_raises(monkeypatch):
    import kortex_search.sources.baidu as bd
    monkeypatch.setattr(bd, "CN_SOURCES", True)
    # cards present but structurally unrecognized → loud drift, never [].
    async def _fake(*_a, **_k):
        return {"data": {"cards": [{"bogus": 1}]}}
    monkeypatch.setattr(bd, "get_json", _fake)
    with pytest.raises(SourceError, match="shape drift"):
        await bd.BaiduSource().search("")


@pytest.mark.asyncio
async def test_baidu_board_empty_cards_is_empty_board(monkeypatch):
    import kortex_search.sources.baidu as bd
    monkeypatch.setattr(bd, "CN_SOURCES", True)
    async def _fake(*_a, **_k):
        return {"data": {"cards": []}}
    monkeypatch.setattr(bd, "get_json", _fake)
    assert await bd.BaiduSource().search("") == []


# --------------------------------------------------------------------------
# Zhihu hot list (0.4.3: anonymous hot-list source, PHASE8 Plan 2)
# --------------------------------------------------------------------------


def _zhihu_hot_fixture() -> dict:
    import json as _json
    from pathlib import Path
    return _json.loads(
        Path(__file__).parent.joinpath(
            "fixtures/platforms/zhihu_hot.json").read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_zhihu_hot_parses_fixture(monkeypatch):
    import kortex_search.sources.zhihu_hot as zh
    monkeypatch.setattr(zh, "CN_SOURCES", True)
    async def _fake(*_a, **_k):
        return _zhihu_hot_fixture()
    monkeypatch.setattr(zh, "get_json", _fake)
    out = await zh.ZhihuHotSource().search("", limit=10)
    assert len(out) == 10
    first = out[0]
    # URL rewritten to the human surface
    assert first.url.startswith("https://www.zhihu.com/question/")
    assert "api.zhihu.com" not in first.url
    assert first.meta["rank"] == 1
    assert first.meta["answer_count"] >= 0
    assert first.meta["follower_count"] is not None
    assert first.title
    # query filtering
    q = first.title[:8]
    filtered = await zh.ZhihuHotSource().search(q, limit=10)
    assert filtered and filtered[0].title == first.title


@pytest.mark.asyncio
async def test_zhihu_hot_limit_capped_at_30(monkeypatch):
    import kortex_search.sources.zhihu_hot as zh
    monkeypatch.setattr(zh, "CN_SOURCES", True)
    async def _fake(*_a, **_k):
        return _zhihu_hot_fixture()
    monkeypatch.setattr(zh, "get_json", _fake)
    out = await zh.ZhihuHotSource().search("", limit=50)
    assert len(out) == 30  # endpoint cap


@pytest.mark.asyncio
async def test_zhihu_hot_shape_drift_raises(monkeypatch):
    import kortex_search.sources.zhihu_hot as zh
    monkeypatch.setattr(zh, "CN_SOURCES", True)
    async def _fake(*_a, **_k):
        return {"data": "junk"}
    monkeypatch.setattr(zh, "get_json", _fake)
    with pytest.raises(SourceError, match="shape drift"):
        await zh.ZhihuHotSource().search("")


@pytest.mark.asyncio
async def test_zhihu_hot_cn_gated(monkeypatch):
    import kortex_search.sources.zhihu_hot as zh
    monkeypatch.setattr(zh, "CN_SOURCES", False)
    with pytest.raises(SourceError, match="disabled"):
        await zh.ZhihuHotSource().search("x")


@pytest.mark.asyncio
async def test_cn_sources_disabled_by_default():
    import kortex_search.sources.baidu as bd
    import kortex_search.sources.toutiao as tt
    import kortex_search.sources.zhihu_hot as zh
    for src in (bd.BaiduSource(), zh.ZhihuHotSource(), tt.ToutiaoSource()):
        with pytest.raises(SourceError, match="disabled"):
            await src.search("x")


# --------------------------------------------------------------------------
# read_url SSRF hardening (sweep 2026-08-31): encoded jina targets +
# per-hop redirect guards
# --------------------------------------------------------------------------

class TestReadUrlHardening:
    def test_jina_url_percent_encodes_target(self):
        from kortex_search.sources.web import _jina_url
        out = _jina_url("https://example.com/a?b=1#frag")
        # no delimiter smuggling: the target is one encoded path segment —
        # no raw '://', '?', '#' or '//' inside our request path
        assert out.startswith("https://r.jina.ai/")
        path = out.removeprefix("https://r.jina.ai/")
        assert "://" not in path and "?" not in path and "#" not in path
        assert path == "https%3A%2F%2Fexample.com%2Fa%3Fb%3D1%23frag"

    def test_jina_url_smuggling_payloads_are_neutralized(self):
        from kortex_search.sources.web import _jina_url
        for payload in ("//169.254.169.254/latest/meta-data",
                        "https://x.com@169.254.169.254/",
                        "http://127.0.0.1:6379/",
                        "..%2F..%2Fetc"):
            out = _jina_url(payload)
            path = out.removeprefix("https://r.jina.ai/")
            # always a single path segment: no unencoded '/' allowed
            assert "/" not in path

    def test_hop_guard_blocks_private_redirect_target(self, monkeypatch):
        from kortex_search.extract.egress import EgressBlocked
        from kortex_search.sources import web

        class FakeURL:
            def __init__(self, raw):
                self._u = raw
                self.scheme = raw.split(":")[0]

            def __str__(self):
                return self._u

        class FakeReq:
            def __init__(self, raw):
                self.url = FakeURL(raw)

        with pytest.raises(EgressBlocked, match="egress-floor"):
            web._hop_guard(FakeReq("http://169.254.169.254/latest/meta-data"))
        with pytest.raises(EgressBlocked, match="egress-floor"):
            web._hop_guard(FakeReq("https://10.0.0.8/admin"))

    def test_hop_guard_rejects_non_http_schemes(self):
        from kortex_search.sources import web

        class FakeURL:
            def __init__(self, raw):
                self._u = raw
                self.scheme = raw.split(":")[0]

            def __str__(self):
                return self._u

        class FakeReq:
            def __init__(self, raw):
                self.url = FakeURL(raw)

        with pytest.raises(SourceError, match="scheme"):
            web._hop_guard(FakeReq("file:///etc/passwd"))
        with pytest.raises(SourceError, match="scheme"):
            web._hop_guard(FakeReq("gopher://127.0.0.1:6379/"))

    def test_hop_guard_passes_public_target(self, monkeypatch):
        from kortex_search.sources import web

        class FakeURL:
            def __init__(self, raw):
                self._u = raw
                self.scheme = raw.split(":")[0]

            def __str__(self):
                return self._u

        class FakeReq:
            def __init__(self, raw):
                self.url = FakeURL(raw)

        web._hop_guard(FakeReq("https://example.com/page"))  # must not raise


# --------------------------------------------------------------------------
# v0.7 sources: hackernews (Algolia) + wikipedia (MediaWiki)
# --------------------------------------------------------------------------

def test_hackernews_parses_stories(monkeypatch):
    import kortex_search.sources.hackernews as mod
    _mock_http(monkeypatch, mod, [FakeResp({"hits": [
        {"title": "Common mistakes in PostgreSQL", "url": "https://wiki.postgresql.org/x",
         "objectID": "19817531", "points": 1084, "num_comments": 253,
         "created_at": "2019-05-03T11:52:08Z", "author": "kawera"},
        # comment hits carry no url — the item link must be synthesized
        {"title": None, "story_title": "Show HN: My Tool",
         "objectID": "777", "story_id": "777", "points": 42, "num_comments": 0,
         "created_at": "2026-08-30T10:00:00Z"},
        # junk hit without any title — skipped, not crashed
        {"objectID": "9"},
    ]})])

    async def run():
        out = await _r("hackernews").search("postgres")
        assert len(out) == 2
        assert out[0].url == "https://wiki.postgresql.org/x"
        assert out[0].published == "2019-05-03T11:52:08Z"
        assert out[0].meta["points"] == 1084
        assert out[1].url == "https://news.ycombinator.com/item?id=777"
        assert out[1].title == "Show HN: My Tool"

    asyncio.run(run())


def test_wikipedia_parses_and_strips_html(monkeypatch):
    import kortex_search.sources.wikipedia as mod
    _mock_http(monkeypatch, mod, [FakeResp({"query": {"search": [
        {"title": "PostgreSQL", "snippet": '<span class="searchmatch">PostgreSQL</span>'
                                          " is a database",
         "timestamp": "2026-08-24T16:10:56Z", "wordcount": 9189, "pageid": 23824},
        {"title": "A/B testing?", "snippet": "split test",
         "timestamp": "2026-01-01T00:00:00Z", "pageid": 5},
    ]}})])

    async def run():
        out = await _r("wikipedia").search("postgres")
        assert out[0].title == "PostgreSQL"
        assert out[0].snippet == "PostgreSQL is a database"  # tags stripped
        assert out[0].published == "2026-08-24T16:10:56Z"
        # identifier-injection lesson: special chars must be URL-quoted
        assert out[1].url == "https://en.wikipedia.org/wiki/A%2FB%20testing%3F"
        assert out[0].meta["wordcount"] == 9189

    asyncio.run(run())
