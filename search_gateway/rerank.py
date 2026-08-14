# -*- coding: utf-8 -*-
"""Semantic re-ranking with a local cross-encoder (CPU).

Lazily loads BAAI/bge-reranker-v2-m3 (multilingual, EN+ZH) — the best
cross-encoder that fits a CPU-only 16 GB machine. The model is a singleton so
it is loaded once per process; re-ranking is applied only to the top RRF
candidates (never the full result set) to bound CPU latency.
"""

from __future__ import annotations

import logging
from typing import Optional

from .config import RERANK_MODEL, RERANK_REVISION, SEMANTIC_RERANK
from .models import Result

logger = logging.getLogger("search_gateway.rerank")

_model: Optional[object] = None
_model_error: Optional[str] = None


def _get_model():
    global _model, _model_error
    if _model is not None or _model_error is not None:
        return _model
    try:
        from sentence_transformers import CrossEncoder
        logger.info("loading cross-encoder %s ...", RERANK_MODEL)
        kwargs = {"revision": RERANK_REVISION} if RERANK_REVISION else {}
        _model = CrossEncoder(RERANK_MODEL, **kwargs)
        logger.info("cross-encoder loaded")
    except Exception as exc:  # noqa: BLE001 — never crash the search
        _model_error = f"{type(exc).__name__}: {exc}"
        logger.error("cross-encoder load failed: %s", _model_error)
        _model = None
    return _model


def rerank(query: str, candidates: list[Result], top_k: Optional[int] = None) -> list[Result]:
    """Re-rank candidates by query-document relevance. Falls back to input
    order (RRF) if the model is unavailable or disabled. `top_k` optionally
    truncates (else returns the full re-ranked list, so MMR can diversify)."""
    if not candidates or not SEMANTIC_RERANK:
        out = list(candidates)
        return out[:top_k] if top_k else out

    model = _get_model()
    if model is None:
        out = list(candidates)
        return out[:top_k] if top_k else out

    try:
        pairs = [(query, (r.snippet or r.title)[:512]) for r in candidates]
        scores = model.predict(pairs)
        for r, s in zip(candidates, scores):
            r.score = float(s)
        ranked = sorted(candidates, key=lambda r: r.score, reverse=True)
        return ranked[:top_k] if top_k else ranked
    except Exception as exc:  # noqa: BLE001
        logger.error("re-rank failed: %s", exc)
        out = list(candidates)
        return out[:top_k] if top_k else out


def status() -> dict:
    return {"enabled": SEMANTIC_RERANK, "model": RERANK_MODEL,
            "loaded": _model is not None, "error": _model_error}
