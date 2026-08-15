# -*- coding: utf-8 -*-
"""Gateway configuration — env-overridable, machine-specific defaults."""

import os


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- infrastructure ---
SEARXNG_BASE = _env("SEARXNG_BASE", "http://127.0.0.1:8888")
REDIS_URL = _env("SEARCH_GATEWAY_REDIS_URL", "redis://127.0.0.1:6379/0")
GITHUB_TOKEN = _env("GITHUB_TOKEN", "")  # optional, raises API rate limit

# --- search behaviour ---
# Fast, non-browser sources are the default fan-out (opencli sources are
# serialized through one browser bridge, so they're opt-in via `sources`).
DEFAULT_SOURCES = ["searxng", "exa", "github", "youtube", "bilibili", "v2ex"]
WEB_SOURCES = ["searxng", "exa"]
SOCIAL_SOURCES = ["twitter", "reddit", "facebook", "instagram"]
ACADEMIC_SOURCES = ["arxiv", "openalex", "crossref"]  # semantic_scholar optional
# polite-pool email for OpenAlex/Crossref (not an API key — just courteous)
MAILTO = _env("SEARCH_GATEWAY_MAILTO", "kaichen.research@proton.me")
DEFAULT_LIMIT = 10
GLOBAL_TIMEOUT = _env_int("SEARCH_GATEWAY_TIMEOUT", 50)  # seconds per search
PER_SOURCE_TIMEOUT = _env_int("SEARCH_GATEWAY_SOURCE_TIMEOUT", 18)

# --- retry (Phase 3) ---
RETRY_COUNT = _env_int("SEARCH_GATEWAY_RETRY_COUNT", 1)
RETRY_BACKOFF = _env_float("SEARCH_GATEWAY_RETRY_BACKOFF", 1.5)  # seconds, x2 per retry
RETRYABLE_EXIT_CODES = (1, 8, 52, 56)  # curl-style transient codes; skip on auth/404

# --- rate limiting for cookie-logged sources (Phase 3) ---
RATE_LIMITED_SOURCES = {"twitter", "reddit", "facebook", "instagram"}
RATE_LIMIT_INTERVAL = _env_float("SEARCH_GATEWAY_RATE_LIMIT", 2.5)  # min seconds between queries

# --- fusion / re-rank / diversity (Phases 1-2) ---
RRF_K = 60
WEIGHTED_RRF = _env_bool("SEARCH_GATEWAY_WEIGHTED_RRF", True)
RERANK_MODEL = _env("SEARCH_GATEWAY_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
EMBED_MODEL = _env("SEARCH_GATEWAY_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
# Multilingual embedding model for CJK-heavy runs (bilibili/v2ex/XHS dominate).
# Lazy-loaded only when a run's fused results are CJK-dominant; MiniLM stays the
# fast default for English-dominant text.
EMBED_MODEL_CJK = _env("SEARCH_GATEWAY_EMBED_MODEL_CJK", "BAAI/bge-m3")
# Pinned HF revisions (empty string = unpinned). Fixes the observed bge-m3
# commit-churn re-download bug: without `revision=`, snapshot_download /
# SentenceTransformer re-fetch whenever the model repo's HEAD moves.
RERANK_REVISION = _env("SEARCH_GATEWAY_RERANK_REVISION",
                       "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e")
EMBED_REVISION = _env("SEARCH_GATEWAY_EMBED_REVISION",
                      "1110a243fdf4706b3f48f1d95db1a4f5529b4d41")
EMBED_CJK_REVISION = _env("SEARCH_GATEWAY_EMBED_CJK_REVISION",
                          "5617a9f61b028005a4858fdac845db406aefb181")
EMBED_CJK = _env_bool("SEARCH_GATEWAY_EMBED_CJK", True)

# --- inference backend (ONNX, ~2x faster rerank) ---
# torch | onnx (fp32) | onnx_int8 (dynamic-quantized). ONNX needs the
# `.[onnx]` extra (optimum + onnxruntime); if the ONNX model cannot load, the
# reranker falls back to torch automatically.
INFERENCE_BACKEND = _env("SEARCH_GATEWAY_INFERENCE_BACKEND", "torch")
RERANK_ONNX_MODEL = _env("SEARCH_GATEWAY_RERANK_ONNX_MODEL",
                         "onnx-community/bge-reranker-v2-m3-ONNX")
RERANK_ONNX_REVISION = _env("SEARCH_GATEWAY_RERANK_ONNX_REVISION",
                            "6f5ff65298512715a1e669753bc754d2bc8f367b")
# onnx -> model.onnx (fp32); onnx_int8 -> model_int8.onnx (dynamic-quantized).
_ONNX_FILE = {"onnx": "model.onnx", "onnx_int8": "model_int8.onnx"}
CJK_SHARE_THRESHOLD = _env_float("SEARCH_GATEWAY_CJK_SHARE_THRESHOLD", 0.25)
SEMANTIC_RERANK = _env_bool("SEMANTIC_RERANK", True)
RERANK_CANDIDATES = _env_int("SEARCH_GATEWAY_RERANK_CANDIDATES", 30)
MMR_ENABLED = _env_bool("SEARCH_GATEWAY_MMR", True)
MMR_LAMBDA = _env_float("SEARCH_GATEWAY_MMR_LAMBDA", 0.75)  # relevance vs diversity
EMBEDDING_DEDUP = _env_bool("SEARCH_GATEWAY_EMBEDDING_DEDUP", True)

# --- freshness (Phase 3) ---
FRESHNESS_FILTER = _env_bool("SEARCH_GATEWAY_FRESHNESS", True)

# --- two-tier / opencli parallelism (Phase 4) ---
TWO_TIER = _env_bool("SEARCH_GATEWAY_TWO_TIER", True)
OPENCLI_PROFILES = _env_int("SEARCH_GATEWAY_OPENCLI_PROFILES", 1)  # N Chromium profiles

# --- cache (Phase 1) ---
CACHE_TTL = _env_int("SEARCH_GATEWAY_CACHE_TTL", 3600)  # final-result TTL (1h)
SOURCE_CACHE_TTL = _env_int("SEARCH_GATEWAY_SOURCE_CACHE_TTL", 900)  # per-source TTL (15m)

# --- LLM / answer synthesis (Phase 5) ---
DEEPSEEK_API_KEY = _env("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = _env("SEARCH_GATEWAY_LLM_MODEL", "deepseek-v4-flash")
LLM_ENABLED = _env_bool("SEARCH_GATEWAY_LLM", True)
LLM_TIMEOUT = _env_int("SEARCH_GATEWAY_LLM_TIMEOUT", 60)
QUERY_EXPANSION = _env_bool("SEARCH_GATEWAY_QUERY_EXPANSION", True)

# --- auth ---
TWITTER_ENV_FILE = _env("TWITTER_AUTH_FILE", os.path.expanduser("~/.agent-reach/twitter-auth.env"))
DEEPSEEK_ENV_FILE = _env("DEEPSEEK_AUTH_FILE", os.path.expanduser("~/.agent-reach/deepseek.env"))

# --- observability / serving (Phase D) ---
LOG_FMT = _env("SEARCH_GATEWAY_LOG_FMT", "text")  # text | json (always stderr)
LOG_LEVEL = _env("SEARCH_GATEWAY_LOG_LEVEL", "INFO")
MCP_HOST = _env("SEARCH_GATEWAY_HOST", "127.0.0.1")  # bind host for http/sse serve
MCP_PORT = _env_int("SEARCH_GATEWAY_PORT", 8765)     # bind port for http/sse serve

# --- ledger health (Phase 4.6) ---
# Where deep-research run directories (containing ledger.json) live. Used by
# `doctor` / `stats_report` to report run/claim/open-claim health. Read-only.
LEDGER_DIR = _env("SEARCH_GATEWAY_LEDGER_DIR", os.path.expanduser("~/research_runs"))


def load_env_file(path: str, keys: set[str]) -> dict[str, str]:
    """Load `KEY=VALUE` lines from a file (export-aware, quote-stripped)."""
    out: dict[str, str] = {}
    if not path or not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k.startswith("export "):
                k = k[len("export "):]
            if k in keys:
                out[k] = v.strip().strip('"').strip("'")
    return out
