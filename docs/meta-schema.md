# Result.meta — Standardized Schema

`Result` is the universal contract across all 18 sources: it is what sources
emit, what fusion/re-rank/dedup consume, and what the report skills read. Its
`meta` field is a free-form `dict[str, Any]`; this document defines the
**standardized keys** that sources populate. Every key is **optional and
backward-compatible** — absence means "unknown", never an error. The contract
is enforced structurally by `tests/test_contract.py`.

## Top-level fields

| Field | Type | Notes |
|-------|------|-------|
| `title` | str | |
| `url` | str | |
| `snippet` | str | excerpt / abstract / body |
| `source` | str | gateway source name (arxiv, openalex, twitter, …) |
| `engine` | str | underlying backend (openalex, bing, opencli, …) |
| `published` | str\|None | raw date string |
| `score` | float | final score — cross-encoder relevance after re-rank, or RRF |
| `meta` | dict | see below |

## `meta` keys

### Classification (set automatically for every source)

| Key | Type | Values |
|-----|------|--------|
| `source_type` | str | `paper` \| `post` \| `video` \| `repo` \| `web` \| `forum` \| `news` \| `doc` \| `code` |

Mapping: `paper`→arxiv/openalex/crossref/semantic_scholar · `web`→searxng/exa/web ·
`video`→youtube/bilibili · `repo`→github · `forum`→v2ex/reddit/stackoverflow ·
`post`→twitter/facebook/instagram/linkedin/xiaohongshu.

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
