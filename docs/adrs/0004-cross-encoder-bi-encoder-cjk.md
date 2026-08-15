# 0004: cross-encoder re-rank; bi-encoder dedup/MMR; lazy CJK bi-encoder

**Status: Accepted**

## Context

Three distinct jobs need three different kinds of model, and conflating them
wastes either accuracy or latency. Re-ranking needs the sharpest possible
query-document relevance judgment on a small candidate set. Dedup and MMR
diversity need document-to-document similarity across a larger set, cheaply,
which a cross-encoder cannot produce (it scores pairs, not standalone
vectors — `rerank.py`'s docstring notes this directly: "the re-ranker
(bge-reranker-v2-m3) is a cross-encoder and can't produce standalone
vectors"). And most of the fused set is English-dominant, but bilibili,
v2ex, and Xiaohongshu results mean CJK text is a real, recurring case that an
English-only embedding model handles poorly.

## Decision

Three models, three jobs. `SEARCH_GATEWAY_RERANK_MODEL` defaults to
`BAAI/bge-reranker-v2-m3` — a multilingual (EN+ZH) cross-encoder, applied only
to the top `RERANK_CANDIDATES=30` RRF survivors, to bound CPU latency on a
16 GB host (`rerank.py`). `SEARCH_GATEWAY_EMBED_MODEL` defaults to
`sentence-transformers/all-MiniLM-L6-v2` — a fast bi-encoder for dedup and
MMR similarity on English-dominant text. `SEARCH_GATEWAY_EMBED_MODEL_CJK`
defaults to `BAAI/bge-m3` — a larger multilingual bi-encoder, loaded lazily
only when `embeddings.cjk_dominant()` finds the fused document set's combined
CJK character share at or above `SEARCH_GATEWAY_CJK_SHARE_THRESHOLD=0.25`.
All three are process-level singletons, loaded once and cached in module
globals (`_model`, `_cjk_model` in `embeddings.py`; `_model` in `rerank.py`).

## Consequences

- The 2.3 GB `bge-m3` model only loads into memory for runs that are actually
  CJK-dominant — an English-only deployment (or an English-only query mix)
  never pays that memory or load-time cost.
- Re-rank scope is deliberately narrow (top 30, not the full fused set) —
  this bounds worst-case CPU latency regardless of how many results a query
  fans out to, at the cost of never re-ranking a candidate ranked 31st or
  below by RRF, however relevant it might actually be.
- Dedup and MMR share the same bi-encoder selection logic
  (`cjk_dominant()` decides once per search, and both stages reuse that
  decision) — so the CJK/English model choice is consistent within one
  request, never mixed mid-pipeline.
- The cross-encoder runs on **ONNX Runtime** (dynamic-quantized INT8) by
  default — `SEARCH_GATEWAY_INFERENCE_BACKEND` selects `onnx_int8`, `onnx`
  (fp32), or `torch`. Measured ~2× faster and ~1GB smaller RSS than torch at
  Spearman ≈ 0.96 ranking agreement; `torch` remains the fallback if the ONNX
  model can't load.