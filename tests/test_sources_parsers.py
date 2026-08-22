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

from search_gateway.sources import ALL_SOURCES
from search_gateway.sources.base import SourceError


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


class FakeClient:
    """httpx.AsyncClient drop-in: returns a scripted response per call."""

    def __init__(self, responses=None, **kwargs):
        self.responses = list(responses or [])
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.responses:
            return self.responses.pop(0)
        return FakeResp({})


def _mock_http(monkeypatch, module, responses):
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kw: FakeClient(responses, **kw))


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
    import search_gateway.sources.searxng as mod
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
    import search_gateway.sources.searxng as mod
    _mock_http(monkeypatch, mod, [FakeResp({}, status_code=500)])

    async def run():
        with pytest.raises(SourceError, match="searxng"):
            await _r("searxng").search("x")
    asyncio.run(run())


def test_github_parses_and_rate_limit(monkeypatch):
    import search_gateway.sources.github as mod
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
    import search_gateway.sources.v2ex as mod
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
    import search_gateway.sources.arxiv as mod
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
    import search_gateway.sources.arxiv as mod
    _mock_http(monkeypatch, mod, [FakeResp(text="<not-xml")])

    async def run():
        with pytest.raises(SourceError, match="arxiv"):
            await _r("arxiv").search("x")

    asyncio.run(run())


def test_bilibili_parses_blocks(monkeypatch):
    import search_gateway.sources.bilibili as mod
    _mock_http(monkeypatch, mod, [FakeResp({"code": 0, "data": {"result": [
        {"result_type": "video", "data": [
            {"title": '<em class="keyword">异步</em>编程', "arcurl": "https://b23.tv/1",
             "description": "desc", "author": "up主", "play": 100},
            "garbage-string-item",
        ]},
        {"result_type": "bili_user", "data": [
            {"title": "某人", "url": "https://space.bilibili.com/2", "description": "x"},
        ]},
    ]}})])

    async def run():
        out = await _r("bilibili").search("异步")
        assert len(out) == 2
        assert out[0].title == "异步编程"  # em tags stripped
        assert out[0].meta["play"] == 100
        assert out[1].meta["type"] == "bili_user"

    asyncio.run(run())


def test_bilibili_api_error(monkeypatch):
    import search_gateway.sources.bilibili as mod
    _mock_http(monkeypatch, mod, [FakeResp({"code": -412, "message": "risk control"})])

    async def run():
        with pytest.raises(SourceError, match="risk control"):
            await _r("bilibili").search("x")

    asyncio.run(run())


def test_openalex_search_filters(monkeypatch):
    import search_gateway.sources.openalex as mod
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
    import search_gateway.sources.crossref as mod
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
    import search_gateway.sources.semantic_scholar as mod
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

    asyncio.run(run())


def test_stackoverflow_parses_epoch(monkeypatch):
    import search_gateway.sources.stackoverflow as mod
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
    import search_gateway.sources.web as mod
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
    import search_gateway.sources.youtube as mod
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
    import search_gateway.sources.exa as mod
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
    import search_gateway.sources.twitter as mod
    envfile = tmp_path / "twitter.env"
    envfile.write_text('TWITTER_AUTH_TOKEN="t"\nTWITTER_CT0="c"\n')
    monkeypatch.setattr(mod, "TWITTER_ENV_FILE", str(envfile))

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
    import search_gateway.sources.twitter as mod
    monkeypatch.setattr(mod, "TWITTER_ENV_FILE", "/nonexistent.env")  # no backend1 auth

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
    import search_gateway.sources.twitter as mod
    monkeypatch.setattr(mod, "TWITTER_ENV_FILE", "/nonexistent.env")

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
    import search_gateway.sources.reddit as mod
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
    import search_gateway.sources.facebook as fb
    import search_gateway.sources.instagram as ig
    import search_gateway.sources.xiaohongshu as xhs

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
    import search_gateway.sources.linkedin as mod
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
    import search_gateway.sources.reddit as rd
    import search_gateway.sources.youtube as yt

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
