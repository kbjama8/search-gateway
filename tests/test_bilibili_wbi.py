"""Bilibili wbi signing tests — canonical worked example from
bilibili-API-collect (docs/misc/sign/wbi.md, LESSONS.md §3.4).

The doc's worked values:
  img_key  = 7cd084941338484aae1ad9425b84077c
  sub_key  = 4932caff0ff746eab6f01bf08b70ac45
  mixin    = ea1db124af3c7062474693fa704f4ff8
  params   = {foo: '114', bar: '514', zab: 1919810}, wts = 1702204169
  w_rid    = 8f6f2b5b3d485fe1886cec6a0be8c5d4
"""

from __future__ import annotations

import pytest

from search_gateway.sources.bilibili import (
    _encode,
    mixin_key,
    sign_params,
)

IMG = "7cd084941338484aae1ad9425b84077c"
SUB = "4932caff0ff746eab6f01bf08b70ac45"
WTS = 1702204169


def test_mixin_key_canonical():
    assert mixin_key(IMG, SUB) == "ea1db124af3c7062474693fa704f4ff8"


def test_mixin_key_truncates_to_32():
    assert len(mixin_key(IMG, SUB)) == 32


def test_sign_params_canonical_wrid():
    out = sign_params({"foo": "114", "bar": "514", "zab": 1919810},
                      IMG, SUB, wts=WTS)
    assert out["w_rid"] == "8f6f2b5b3d485fe1886cec6a0be8c5d4"
    assert out["wts"] == WTS
    # original params preserved (order/type untouched), signed fields appended
    assert out["foo"] == "114" and out["bar"] == "514" and out["zab"] == 1919810


def test_encode_uri_component_semantics():
    # spaces → %20 (NOT +); CJK → uppercase percent-hex; !'()* unencoded
    assert _encode("one one four") == "one%20one%20four"
    assert _encode("五一四") == "%E4%BA%94%E4%B8%80%E5%9B%9B"
    assert _encode("a!b'c(d)e*f") == "a!b'c(d)e*f"


def test_sign_stable_for_fixed_wts():
    a = sign_params({"keyword": "异步"}, IMG, SUB, wts=WTS)
    b = sign_params({"keyword": "异步"}, IMG, SUB, wts=WTS)
    assert a == b
    c = sign_params({"keyword": "异步"}, IMG, SUB, wts=WTS + 1)
    assert a["w_rid"] != c["w_rid"]  # wts is part of the digest


@pytest.mark.asyncio
async def test_search_uses_signed_request(monkeypatch):
    """The search path fetches keys, signs, and requests with w_rid/wts.

    Hermetic: the Redis-backed key cache is stubbed out so the fetch always
    runs through the mocked httpx queue (a warm real Redis would short-
    circuit the nav call and skew the queue order).
    """
    import httpx as _httpx

    import search_gateway.sources.bilibili as mod
    from search_gateway.sources import ALL_SOURCES

    class StubRedis:
        def get(self, k):
            return None

        def set(self, *a, **kw):
            return True

    monkeypatch.setattr(mod, "_get_client", lambda: StubRedis())
    monkeypatch.setattr(mod, "_mem_cache", {"img": "", "sub": "", "at": 0.0})

    class ScriptedClient:
        def __init__(self, responses, **kwargs):
            self.responses = list(responses)
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            resp = self.responses.pop(0)
            resp._url_kwargs = kwargs
            return resp

        async def request(self, method, url, **kwargs):
            return await self.get(url, **kwargs)

    class Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

        @property
        def text(self):
            import json as _json
            return _json.dumps(self._payload)

        @property
        def headers(self):
            return {}

        @property
        def status_code(self):
            return 200

    nav = Resp({"code": -101, "data": {"wbi_img": {
        "img_url": f"https://i0.hdslb.com/bfs/wbi/{IMG}.png",
        "sub_url": f"https://i0.hdslb.com/bfs/wbi/{SUB}.png"}}})
    search_resp = Resp({"code": 0, "data": {"result": []}})
    client = ScriptedClient([nav, search_resp])
    monkeypatch.setattr(_httpx, "AsyncClient", lambda **kw: client)

    out = await ALL_SOURCES["bilibili"].search("x")
    assert out == []
    nav_call, search_call = client.calls
    assert "nav" in nav_call[0]
    params = search_call[1]["params"]
    assert "w_rid" in params and "wts" in params
    assert params["keyword"] == "x"
