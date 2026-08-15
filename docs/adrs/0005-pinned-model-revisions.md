# 0005: pin Hugging Face model revisions

**Status: Accepted**

## Context

Without an explicit `revision=`, `snapshot_download` and `SentenceTransformer`
re-resolve to whatever commit is currently `HEAD` on the model repo — an
observed, specific failure mode noted directly in `embeddings.py`'s loader:
"without `revision=`, `snapshot_download`/`SentenceTransformer` re-fetch
whenever the model repo's HEAD moves." On a host process that's supposed to
keep a warm model cache indefinitely, an upstream commit on the model
repository (not this repo) silently triggers a multi-gigabyte re-download the
next time the model loads — for `bge-m3` alone, that's roughly 2.3 GB,
unprompted by anything the gateway's own operator did.

## Decision

Every model has a corresponding `*_REVISION` env var pinning a specific
Hugging Face commit SHA, passed as `revision=` to `snapshot_download`
(`embeddings.py`) and `CrossEncoder(...)` (`rerank.py`). The three defaults —
`SEARCH_GATEWAY_RERANK_REVISION`, `SEARCH_GATEWAY_EMBED_REVISION`,
`SEARCH_GATEWAY_EMBED_CJK_REVISION` — pin `bge-reranker-v2-m3`,
`all-MiniLM-L6-v2`, and `bge-m3` respectively to known-good shas. An empty
string means unpinned — supported for intentionally tracking a model repo's
latest commit, but that reintroduces the exact re-download risk this decision
exists to prevent.

## Consequences

- Model loads are deterministic and reproducible across machines and
  restarts: the same pinned sha resolves to the same weights every time,
  independent of what the model's maintainers push upstream.
- Upgrading a model deliberately (a newer, better checkpoint) is now an
  explicit, single-line change — update the `*_REVISION` value and run
  `search-gateway warm` to force the new download once, rather than letting
  it happen implicitly on some future live query
  (`docs/deployment.md#upgrade-path`).
- The cost is a small amount of operational awareness: leaving a `*_REVISION`
  unset silently reopens the commit-churn re-download risk, so
  `docs/config-reference.md` calls this out as a variable worth actively
  choosing, not leaving at a default value one might assume is "unset means
  safe."