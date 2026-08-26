"""Browser scheduling — budget, pacing, jitter.

Replaces the single global `OPENCLI_LOCK` (one semaphore for ALL browser
traffic) with a configurable browser budget plus per-name pacing with jitter.
A fixed inter-query interval is itself a fingerprint; jittered pacing is the
cheapest anti-detection there is (PLAN.md doctrine #4).
"""

from __future__ import annotations

import asyncio
import contextlib
import random

from ..config import BROWSER_BUDGET, RATE_LIMIT_JITTER

_budget: asyncio.Semaphore | None = None
_last: dict[str, float] = {}


def _get_budget() -> asyncio.Semaphore:
    global _budget
    if _budget is None:
        _budget = asyncio.Semaphore(max(1, BROWSER_BUDGET))
    return _budget


@contextlib.asynccontextmanager
async def browser_lease(name: str):
    """Acquire one unit of the global browser budget. Default budget is 1
    (the old single-bridge behavior, unchanged); the profile farm raises it
    once parallel profiles exist."""
    async with _get_budget():
        yield


def jitter(interval: float) -> float:
    """interval x uniform(1±RATE_LIMIT_JITTER); floor at 0.25s."""
    if interval <= 0:
        return 0.0
    frac = RATE_LIMIT_JITTER if 0 < RATE_LIMIT_JITTER < 1 else 0.0
    # jitter is pacing, not entropy — non-crypto RNG is correct here
    return max(0.25, interval * (1 + random.uniform(-frac, frac)))  # noqa: S311


async def paced(name: str, interval: float) -> None:
    """Sleep out the remainder of `interval` (jittered) since the last call
    under `name`. In-memory only — cross-process pacing stays in
    `ratelimit.wait_if_needed`; this is the per-profile smoothing layer."""
    loop = asyncio.get_running_loop()
    now = loop.time()
    wait = _last.get(name, 0.0) + jitter(interval) - now
    if wait > 0:
        await asyncio.sleep(wait)
    _last[name] = loop.time()
