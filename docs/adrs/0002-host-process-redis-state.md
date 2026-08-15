# 0002: the gateway is a host process; Redis owns shared state

**Status: Accepted**

## Context

The gateway shells out to CLIs (`opencli`, `twitter`, `yt-dlp`, `uvx`,
`mcporter`) and keeps a warm Hugging Face model cache
(`~/.cache/huggingface`) across the process lifetime — the cross-encoder and
bi-encoders load lazily once and stay resident (`rerank.py`, `embeddings.py`
both use module-level singletons: `_model`/`_model_error`). None of that
dockerizes cleanly: a container restart drops the warm model cache and most
CLI+browser dependencies assume a persistent host filesystem and, for social
sources, a persistent browser profile. Meanwhile, the gateway needs shared
state across restarts and across whatever number of client-spawned processes
are running at once — cache, per-source reliability stats, rate-limit gates,
and saved queries.

## Decision

The gateway itself stays a host process — not containerized in the primary
deployment path (a headless "minimal" tier Docker image exists for
CI/academic-only use, per `docs/deployment.md`, but it's explicitly a reduced
tier, not the default). Redis owns everything that needs to survive process
restarts or be shared across concurrent gateway processes: the final and
per-source result cache (`cache.py`), rolling 24h reliability/latency stats
(`stats.py`), the rate-limit gate for cookie-logged sources (`ratelimit.py`),
and `saved_queries` (`saved_queries.py`). Redis itself *does* containerize
cleanly and runs via `infra/docker-compose.yml` with AOF (append-only file)
persistence enabled, so that shared state survives a Redis container restart.

## Consequences

- Every stateful module (`cache.py`, `stats.py`, `ratelimit.py`,
  `saved_queries.py`) follows the same pattern: lazy Redis client, every call
  wrapped in `except redis.RedisError`, logged at `debug`, degrading to a
  miss/no-op rather than raising. A Redis outage costs functionality
  (caching, rate-limit coordination, reliability weighting), never
  correctness — `search` still returns results.
- `saved_queries` — the one piece of genuinely user-owned state, not just a
  cache — depends entirely on Redis AOF for durability. Losing the Redis
  volume without a backup loses saved queries permanently
  (`docs/deployment.md#troubleshooting` covers the AOF backup step).
- Two gateway processes (e.g. one stdio session per client, run concurrently)
  share reliability stats and rate-limit state correctly because both talk to
  the same Redis instance — the alternative (in-process state) would let two
  concurrent gateways independently exceed the rate-limit interval on a
  cookie-logged source.