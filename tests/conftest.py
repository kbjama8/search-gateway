"""Shared hermetic Redis stub + fixtures for the gateway test suite."""

from __future__ import annotations

import os
import time

import pytest

# Local integration tests hit the real Redis, which is now password-protected
# (B6 hardening). Load the gateway env before any module imports config so the
# REDIS_URL carries the credentials. CI spins its own unauthenticated redis —
# no env file there, defaults apply.
_GATEWAY_ENV = os.path.expanduser("~/.agent-reach/gateway.env")
if os.path.exists(_GATEWAY_ENV):
    with open(_GATEWAY_ENV, encoding="utf-8") as _fh:
        for _line in _fh:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))


class PipelineStub:
    def __init__(self, stub):
        self._s = stub
        self._ops = []

    def incr(self, k):
        self._ops.append(("incr", k))
        return self

    def incrbyfloat(self, k, v):
        self._ops.append(("incrbyfloat", k, v))
        return self

    def expire(self, k, t):
        self._ops.append(("expire", k, t))
        return self

    def rpush(self, k, v):
        self._ops.append(("rpush", k, v))
        return self

    def ltrim(self, k, lo, hi):
        self._ops.append(("ltrim", k, lo, hi))
        return self

    def execute(self):
        for op in self._ops:
            if op[0] == "incr":
                self._s.incr(op[1])
            elif op[0] == "incrbyfloat":
                self._s.incrbyfloat(op[1], op[2])
            elif op[0] == "expire":
                self._s.expire(op[1], op[2])
            elif op[0] == "rpush":
                self._s.rpush(op[1], op[2])
            elif op[0] == "ltrim":
                self._s.ltrim(op[1], op[2], op[3])
        return [1] * len(self._ops)


class RedisStub:
    def __init__(self):
        self._data: dict[str, str] = {}
        self._lists: dict[str, list[str]] = {}
        self._exp: dict[str, float] = {}

    def _alive(self, k) -> bool:
        exp = self._exp.get(k)
        return exp is None or exp > time.time()

    def get(self, k):
        if self._alive(k) and k in self._data:
            return self._data[k]
        return None

    def set(self, k, v, nx=False, ex=None):
        if nx and self._alive(k) and k in self._data:
            return False
        self._data[k] = v
        if ex is not None:
            self._exp[k] = time.time() + ex
        else:
            self._exp.pop(k, None)
        return True

    def delete(self, k):
        return 1 if self._data.pop(k, None) is not None else 0

    def ttl(self, k):
        exp = self._exp.get(k)
        if exp is None:
            return -1
        return max(0, int(exp - time.time()))

    def expire(self, k, t):
        self._exp[k] = time.time() + t
        return True

    def incr(self, k):
        v = int(self._data.get(k, 0)) + 1
        self._data[k] = str(v)
        return v

    def incrbyfloat(self, k, v):
        cur = float(self._data.get(k, 0.0)) + v
        self._data[k] = str(cur)
        return cur

    def scan_iter(self, pattern):
        prefix = pattern.split("*")[0]
        return [k for k in self._data if k.startswith(prefix)]

    def info(self, section="server"):
        return {"redis_version": "7.2.0"}

    def pipeline(self):
        return PipelineStub(self)

    def rpush(self, k, v):
        self._lists.setdefault(k, []).append(str(v))
        return len(self._lists[k])

    def ltrim(self, k, lo, hi):
        vals = self._lists.get(k, [])
        if hi < 0:
            hi = len(vals) + hi
        if lo < 0:
            lo = max(0, len(vals) + lo)
        self._lists[k] = vals[max(0, lo):hi + 1]
        return True

    def lrange(self, k, lo, hi):
        vals = self._lists.get(k, [])
        if hi < 0:
            hi = len(vals) + hi
        if lo < 0:
            lo = max(0, len(vals) + lo)
        return vals[max(0, lo):hi + 1]




@pytest.fixture
def rds(monkeypatch):
    """Bind every gateway module's `_get_client` to one in-memory RedisStub."""
    stub = RedisStub()

    def bind(module):
        monkeypatch.setattr(module, "_get_client", lambda: stub)

    from kortex_search import cache, ratelimit, stats
    bind(cache)
    bind(ratelimit)
    bind(stats)
    from kortex_search import saved_queries
    bind(saved_queries)
    from kortex_search.extract import profiles, proxies
    bind(profiles)
    bind(proxies)
    return stub


@pytest.fixture(autouse=True)
def _reset_http_pools():
    """Shared httpx pools bind to an event loop — pytest-asyncio spins a
    fresh loop per test, so drop the singletons after every test (they
    re-init lazily in the next one)."""
    yield
    from kortex_search import llm
    from kortex_search.extract import http
    from kortex_search.sources import web
    for mod, attr in ((http, "_client"), (llm, "_client"),
                      (web, "_scrape"), (web, "_scrape_sync")):
        setattr(mod, attr, None)


@pytest.fixture(autouse=True)
def _reset_s2_cooldown():
    """The S2 429 cooldown is process-global module state — reset it after
    every test so a real probe (doctor CLI tests) or a scripted 429 cannot
    leak into later hermetic tests (sweep 2026-09-03)."""
    yield
    from kortex_search.sources import semantic_scholar
    semantic_scholar._until = 0.0
