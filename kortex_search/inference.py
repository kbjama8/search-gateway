"""Off-loop model inference shim (sweep 2026-09-03).

The cross-encoder re-ranker and the bi-encoder embedders are CPU-bound and
lazy-loaded. Running them synchronously inside an async tool handler froze
the MCP event loop for tens of seconds (imports + model loads + batches).
Phase-0 reproduction measured a single 16.9 s blocking stretch; concurrent
requests queued behind the freeze and the MCP stdio session unwound,
killing the whole server process with a clean rc=0 mid-request.

Every heavy call therefore runs on a dedicated single-worker executor:

  * the event loop stays live — pings, cancellations, and other tool calls
    are serviced while a batch runs (client timeouts become per-request
    errors, never process death);
  * `max_workers=1` serializes inference, which also singleflights lazy
    model loads: concurrent first calls queue on the worker instead of
    loading the same model N times;
  * on client cancellation the executor thread keeps running and its result
    is discarded — safe, since the models are process singletons anyway.

Worker threads are non-daemon by default, so a batch still running at
interpreter shutdown delays exit by at most its remaining runtime
(seconds, bounded).
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ks-model")
    return _executor


async def run_inference(fn, *args, **kwargs):
    """Run a CPU-bound model call off the event loop (serialized).

    Model loads happen inside the worker on first use, so the import +
    download/load cost never blocks the loop either.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_get_executor(), fn, *args, **kwargs)
