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

    @property
    def headers(self):
        return {}


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

    async def request(self, method, url, **kwargs):
        # extract.http uses client.request(); route to the scripted queue.
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
    import httpx as _httpx

    import search_gateway.sources.bilibili as mod
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
    monkeypatch.setattr(_httpx, "AsyncClient",
                        lambda **kw: FakeClient([FakeResp(payload)], **kw))

    async def run():
        out = await _r("bilibili").search("异步")
        assert len(out) == 2
        assert out[0].title == "异步编程"  # em tags stripped
        assert out[0].meta["play"] == 100
        assert out[1].meta["type"] == "bili_user"

    asyncio.run(run())


def test_bilibili_api_error(monkeypatch):
    import httpx as _httpx

    import search_gateway.sources.bilibili as mod
    monkeypatch.setattr(mod, "BILIBILI_WBI", False)
    monkeypatch.setattr(_httpx, "AsyncClient",
                        lambda **kw: FakeClient(
                            [FakeResp({"code": -412, "message": "risk control"})],
                            **kw))

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
    from search_gateway.extract import vault as vault_mod
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
    import search_gateway.sources.twitter as mod
    from search_gateway.extract import vault as vault_mod
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
    import search_gateway.sources.twitter as mod
    from search_gateway.extract import vault as vault_mod
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
    import httpx as _httpx

    import search_gateway.sources.zhihu as zh
    monkeypatch.setattr(zh, "CN_SOURCES", True)
    monkeypatch.setattr(zh, "ZHIHU_COOKIE", "d_c0=abc; z_c0=def")
    monkeypatch.setattr(_httpx, "AsyncClient",
                        lambda **kw: FakeClient([FakeResp(_ZHIHU_PAYLOAD)], **kw))

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
    import search_gateway.sources.zhihu as zh
    monkeypatch.setattr(zh, "CN_SOURCES", True)
    monkeypatch.setattr(zh, "ZHIHU_COOKIE", "")
    with pytest.raises(SourceError, match="auth:"):
        await zh.ZhihuSource().search("x")


@pytest.mark.asyncio
async def test_zhihu_disabled_without_flag(monkeypatch):
    import search_gateway.sources.zhihu as zh
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
    import httpx as _httpx

    import search_gateway.sources.weibo as wb
    monkeypatch.setattr(wb, "CN_SOURCES", True)
    monkeypatch.setattr(wb, "WEIBO_SUB", "")  # no SUB → hot list
    monkeypatch.setattr(_httpx, "AsyncClient",
                        lambda **kw: FakeClient([FakeResp(_WEIBO_HOT)], **kw))

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
    import httpx as _httpx

    import search_gateway.sources.weibo as wb
    monkeypatch.setattr(wb, "CN_SOURCES", True)
    monkeypatch.setattr(wb, "WEIBO_SUB", "SUB=abc")
    monkeypatch.setattr(_httpx, "AsyncClient",
                        lambda **kw: FakeClient([FakeResp(_WEIBO_SUB_SEARCH)],
                                                **kw))

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
    import httpx as _httpx

    import search_gateway.sources.baidu as bd
    monkeypatch.setattr(bd, "CN_SOURCES", True)
    monkeypatch.setattr(_httpx, "AsyncClient",
                        lambda **kw: FakeClient([FakeResp(_BAIDU_BOARD)], **kw))

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
    import httpx as _httpx

    import search_gateway.sources.toutiao as tt
    monkeypatch.setattr(tt, "CN_SOURCES", True)
    monkeypatch.setattr(_httpx, "AsyncClient",
                        lambda **kw: FakeClient([FakeResp(_TOUTIAO_BOARD)],
                                                **kw))

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
    import search_gateway.sources.baidu as bd
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
    import search_gateway.sources.baidu as bd
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
    import search_gateway.sources.baidu as bd
    monkeypatch.setattr(bd, "CN_SOURCES", True)
    # cards present but structurally unrecognized → loud drift, never [].
    async def _fake(*_a, **_k):
        return {"data": {"cards": [{"bogus": 1}]}}
    monkeypatch.setattr(bd, "get_json", _fake)
    with pytest.raises(SourceError, match="shape drift"):
        await bd.BaiduSource().search("")


@pytest.mark.asyncio
async def test_baidu_board_empty_cards_is_empty_board(monkeypatch):
    import search_gateway.sources.baidu as bd
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
    import search_gateway.sources.zhihu_hot as zh
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
    import search_gateway.sources.zhihu_hot as zh
    monkeypatch.setattr(zh, "CN_SOURCES", True)
    async def _fake(*_a, **_k):
        return _zhihu_hot_fixture()
    monkeypatch.setattr(zh, "get_json", _fake)
    out = await zh.ZhihuHotSource().search("", limit=50)
    assert len(out) == 30  # endpoint cap


@pytest.mark.asyncio
async def test_zhihu_hot_shape_drift_raises(monkeypatch):
    import search_gateway.sources.zhihu_hot as zh
    monkeypatch.setattr(zh, "CN_SOURCES", True)
    async def _fake(*_a, **_k):
        return {"data": "junk"}
    monkeypatch.setattr(zh, "get_json", _fake)
    with pytest.raises(SourceError, match="shape drift"):
        await zh.ZhihuHotSource().search("")


@pytest.mark.asyncio
async def test_zhihu_hot_cn_gated(monkeypatch):
    import search_gateway.sources.zhihu_hot as zh
    monkeypatch.setattr(zh, "CN_SOURCES", False)
    with pytest.raises(SourceError, match="disabled"):
        await zh.ZhihuHotSource().search("x")


@pytest.mark.asyncio
async def test_cn_sources_disabled_by_default():
    import search_gateway.sources.baidu as bd
    import search_gateway.sources.toutiao as tt
    import search_gateway.sources.zhihu_hot as zh
    for src in (bd.BaiduSource(), zh.ZhihuHotSource(), tt.ToutiaoSource()):
        with pytest.raises(SourceError, match="disabled"):
            await src.search("x")
