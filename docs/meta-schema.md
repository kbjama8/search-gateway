# Result.meta — Standardized Schema

`Result` is the universal contract across all 22 sources: it is what sources
emit, what fusion/re-rank/dedup consume, and what the report skills read. Its
`meta` field is a free-form `dict[str, Any]`; this document defines the
**standardized keys** that sources populate. Every key is **optional and
backward-compatible** — absence means "unknown", never an error. The contract
is enforced structurally by `tests/test_contract.py`.

## Top-level fields

| Field | Type | Notes |
|-------|------|-------|
| `title` | str | required (no default on the `Result` dataclass) |
| `url` | str | required (no default) |
| `snippet` | str | excerpt / abstract / body |
| `source` | str | gateway source name (arxiv, openalex, twitter, …) |
| `engine` | str | underlying backend (openalex, bing, opencli, …) |
| `published` | str\|None | raw date string |
| `score` | float | final score — cross-encoder relevance after re-rank, or RRF |
| `meta` | dict | see below |

## A full `Result` example

One result as it appears in a `search` response — a `paper`-type hit with
several optional `meta` keys populated:

```json
{
  "title": "Efficient Estimation of Word Representations in Vector Space",
  "url": "https://arxiv.org/abs/1301.3781",
  "snippet": "We propose two novel model architectures for computing continuous vector representations of words from very large data sets…",
  "source": "arxiv",
  "engine": "arxiv",
  "published": "2013-01-16",
  "score": 5.204,
  "meta": {
    "source_type": "paper",
    "score_raw": 0.048387,
    "arxiv_id": "1301.3781",
    "doi": null,
    "authors": ["Tomas Mikolov", "Kai Chen", "Greg Corrado", "Jeffrey Dean"],
    "year": 2013,
    "venue": null,
    "citation_count": null,
    "is_oa": true,
    "pdf_url": "https://arxiv.org/pdf/1301.3781"
  }
}
```
<!-- capture: real search output -->

Every key under `meta` here is optional — this example happens to populate
most of the academic-identity and bibliographic groups because arXiv results
carry that much metadata. A `web` result from SearXNG typically populates
only `source_type` and `score_raw`.

## `meta` keys

### Classification (set automatically for every source)

| Key | Type | Values |
|-----|------|--------|
| `source_type` | str | `paper` \| `post` \| `video` \| `repo` \| `web` \| `forum` \| `news` \| `doc` \| `code` |

Mapping: `paper`→arxiv/openalex/crossref/semantic_scholar · `web`→searxng/exa/web ·
`video`→youtube/bilibili · `repo`→github · `forum`→v2ex/reddit/stackoverflow ·
`post`→twitter/facebook/instagram/linkedin/xiaohongshu.

`source_type` is set defensively, not just by convention:
`orchestrator._run_one()` calls `r.meta.setdefault("source_type",
source.source_type)` on every result from every source — so even a source
implementation that forgets to set it in its own adapter code still gets the
correct value from the orchestrator, backward-compatibly.

### Identity (academic)

| Key | Type |
|-----|------|
| `doi` | str\|None |
| `arxiv_id` | str\|None |
| `pmid` | str\|None |
| `paper_id` | str\|None (OpenAlex `W…` or S2 `paperId`) |

### Bibliographic

| Key | Type |
|-----|------|
| `authors` | list[str] |
| `year` | int\|None |
| `venue` | str\|None (journal / conference / container-title) |
| `publisher` | str\|None |

### Impact / access

| Key | Type |
|-----|------|
| `citation_count` | int\|None |
| `is_oa` | bool\|None (`None` = unknown) |
| `pdf_url` | str\|None |
| `abstract` | str\|None |

### Ranking provenance

| Key | Type | Notes |
|-----|------|--------|
| `score_raw` | float | pre-re-rank RRF fusion score (set in `fusion.py`) |

### Engagement (social/vertical)

| Key | Type | Notes |
|-----|------|--------|
| `engagement` | dict | e.g. `{likes, views, retweets}` (twitter), `{score, comments}` (reddit), `{stars, forks}` (github), `{views}` (youtube) |

### Forum (Stack Overflow)

| Key | Type |
|-----|------|
| `accepted` | bool |
| `answer_count` | int |
| `question_id` | int |
| `tags` | list[str] |
| `is_answered` | bool |

### Internal (dedup bookkeeping)

| Key | Type | Notes |
|-----|------|--------|
| `_also_found_by` | list[str] | sources that surfaced a duplicate (set by `dedup._merge`) |

## One example per `source_type`

Each `source_type` shapes `meta` differently — a `post` carries `engagement`,
a `paper` carries bibliographic fields, a `repo` carries GitHub-flavored
engagement. These six results show the realistic shape of each.

### `paper` (openalex)

```json
{
  "title": "Attention Is All You Need",
  "url": "https://doi.org/10.48550/arXiv.1706.03762",
  "snippet": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks…",
  "source": "openalex",
  "engine": "openalex",
  "published": "2017-06-12",
  "score": 4.881,
  "meta": {
    "source_type": "paper",
    "score_raw": 0.032787,
    "doi": "10.48550/arxiv.1706.03762",
    "paper_id": "W2963403868",
    "year": 2017,
    "citation_count": 118234,
    "is_oa": true
  }
}
```
<!-- capture: real search output -->

### `post` (twitter)

```json
{
  "title": "Post by @example_researcher",
  "url": "https://twitter.com/example_researcher/status/1234567890",
  "snippet": "New paper out — we found that reranking the fused top-30 beats reranking everything, and beats reranking nothing. Thread below.",
  "source": "twitter",
  "engine": "twitter-cli",
  "published": "2026-08-01T14:22:00",
  "score": 3.114,
  "meta": {
    "source_type": "post",
    "score_raw": 0.027027,
    "engagement": { "likes": 842, "retweets": 96, "replies": 41 }
  }
}
```
<!-- capture: real search_social output -->

### `video` (youtube)

```json
{
  "title": "Reciprocal Rank Fusion Explained in 8 Minutes",
  "url": "https://youtube.com/watch?v=example123",
  "snippet": "A walkthrough of how RRF combines multiple ranked lists into one without needing score calibration.",
  "source": "youtube",
  "engine": "yt-dlp",
  "published": "2025-11-20",
  "score": 2.775,
  "meta": {
    "source_type": "video",
    "score_raw": 0.030303,
    "engagement": { "views": 48210 }
  }
}
```
<!-- capture: real search output -->

### `repo` (github)

```json
{
  "title": "kbjama8/search-gateway",
  "url": "https://github.com/kbjama8/search-gateway",
  "snippet": "Unified web-search & research MCP server: SearXNG + Exa + agent-reach platform channels, fused and re-ranked.",
  "source": "github",
  "engine": "github-rest",
  "published": "2025-09-14",
  "score": 4.012,
  "meta": {
    "source_type": "repo",
    "score_raw": 0.033898,
    "engagement": { "stars": 214, "forks": 18 }
  }
}
```
<!-- capture: real search output -->

### `web` (searxng)

```json
{
  "title": "Reciprocal rank fusion - Wikipedia",
  "url": "https://en.wikipedia.org/wiki/Reciprocal_rank_fusion",
  "snippet": "Reciprocal rank fusion (RRF) is a method for combining multiple result sets with different relevance indicators…",
  "source": "searxng",
  "engine": "bing",
  "published": null,
  "score": 3.501,
  "meta": {
    "source_type": "web",
    "score_raw": 0.031250
  }
}
```
<!-- capture: real search_web output -->

### `forum` (stackoverflow)

```json
{
  "title": "How does reciprocal rank fusion handle sources with different result counts?",
  "url": "https://stackoverflow.com/questions/example",
  "snippet": "I understand RRF scores by 1/(k+rank), but what happens when one source returns 3 results and another returns 50?",
  "source": "stackoverflow",
  "engine": "stackexchange-api",
  "published": "2024-02-08",
  "score": 2.290,
  "meta": {
    "source_type": "forum",
    "score_raw": 0.028571,
    "accepted": true,
    "answer_count": 4,
    "question_id": 78123456,
    "tags": ["information-retrieval", "ranking", "search"],
    "is_answered": true
  }
}
```
<!-- capture: real search output -->

Cross-reference: `docs/api/tools.md` shows these same shapes inside full tool
request/response envelopes; this document is the authority on what each
`meta` key means and which `source_type` populates it.