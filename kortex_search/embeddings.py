"""Document embeddings (bi-encoder) for MMR diversity + embedding dedup.

Lazy-loads sentence-transformers/all-MiniLM-L6-v2 (already cached) for the fast
default path. For CJK-dominant runs (bilibili/v2ex/XHS), lazily loads
BAAI/bge-m3 (multilingual) so dedup/MMR embed Chinese/Japanese/Korean text
meaningfully instead of degrading to the English-only MiniLM vectors.

Used for document↔document similarity — the re-ranker (bge-reranker-v2-m3) is a
cross-encoder and can't produce standalone vectors.
"""

from __future__ import annotations

import logging

import numpy as np

from .config import (
    CJK_SHARE_THRESHOLD,
    EMBED_CJK,
    EMBED_CJK_REVISION,
    EMBED_MODEL,
    EMBED_MODEL_CJK,
    EMBED_REVISION,
)
from .inference import run_inference

logger = logging.getLogger("kortex_search.embeddings")

_model: object | None = None
_model_error: str | None = None
_cjk_model: object | None = None
_cjk_model_error: str | None = None


def _load(model_name: str, revision: str = "") -> tuple[object | None, str | None]:
    try:
        from sentence_transformers import SentenceTransformer
        logger.info("loading embed model %s ...", model_name)
        kwargs = {"revision": revision} if revision else {}
        try:
            # Fast path: resolve straight from the local cache (no Hugging Face
            # API round-trip). SentenceTransformer prefers safetensors, so the
            # redundant pytorch_model.bin is never pulled.
            m = SentenceTransformer(model_name, local_files_only=True, **kwargs)
        except Exception:  # noqa: BLE001 — cache miss → fetch below
            # Cache miss → download, skipping the ~2.3GB .bin and onnx exports.
            from huggingface_hub import snapshot_download
            local = snapshot_download(model_name, ignore_patterns=["*.bin", "onnx/*"],
                                      **kwargs)
            m = SentenceTransformer(local)
        logger.info("embed model loaded: %s", model_name)
        return m, None
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
        logger.error("embed model load failed (%s): %s", model_name, err)
        return None, err


def _get_model():
    global _model, _model_error
    if _model is None and _model_error is None:
        _model, _model_error = _load(EMBED_MODEL, EMBED_REVISION)
    return _model


def _get_cjk_model():
    global _cjk_model, _cjk_model_error
    if _cjk_model is None and _cjk_model_error is None:
        _cjk_model, _cjk_model_error = _load(EMBED_MODEL_CJK, EMBED_CJK_REVISION)
    return _cjk_model


def _is_cjk(ch: str) -> bool:
    return ("\u4e00" <= ch <= "\u9fff"       # CJK unified ideographs
            or "\u3040" <= ch <= "\u30ff"    # hiragana/katakana
            or "\uac00" <= ch <= "\ud7af")   # hangul


def cjk_dominant(texts: list[str]) -> bool:
    """True when the combined CJK character share across `texts` exceeds the
    threshold — the signal to switch to the multilingual embed model."""
    if not EMBED_CJK or not texts:
        return False
    total = 0
    cjk = 0
    for t in texts:
        if not t:
            continue
        total += len(t)
        cjk += sum(1 for ch in t if _is_cjk(ch))
    if total == 0:
        return False
    return (cjk / total) >= CJK_SHARE_THRESHOLD


def encode(texts: list[str], multilingual: bool = False) -> np.ndarray | None:
    """Return normalized document vectors (or None if the model is unavailable).

    `multilingual=True` selects the CJK model (bge-m3); leave False for the fast
    English-dominant default.
    """
    if not texts:
        return None
    model = _get_cjk_model() if multilingual else _get_model()
    if model is None:
        return None
    try:
        vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vecs)
    except Exception as exc:  # noqa: BLE001
        logger.error("embed failed: %s", exc)
        return None


async def encode_async(texts: list[str], multilingual: bool = False):
    """Event-loop-safe `encode`: model load + batch run on the shared
    inference worker (see inference.py). Returns None when unavailable."""
    return await run_inference(encode, texts, multilingual)


def cosine_matrix(vecs: np.ndarray) -> np.ndarray:
    """Pairwise cosine similarity (vecs assumed normalized)."""
    return vecs @ vecs.T


def status() -> dict:
    return {
        "model": EMBED_MODEL, "loaded": _model is not None, "error": _model_error,
        "cjk_model": EMBED_MODEL_CJK, "cjk_loaded": _cjk_model is not None,
        "cjk_error": _cjk_model_error, "cjk_enabled": EMBED_CJK,
    }
