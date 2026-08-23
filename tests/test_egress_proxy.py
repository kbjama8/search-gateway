"""L2 EgressProxy tests — real asyncio sockets on loopback, no external net.

CONNECT allow/deny, absolute-URI allow/deny with origin-form rewriting, floor
composition (telemetry), residential chaining (mocked upstream), singleton.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from search_gateway.extract import egress


class EchoServer:
    """Loopback echo server: echoes bytes back, records first request line."""

    def __init__(self):
        self._server = None
        self.port = 0
        self.first_line: bytes | None = None
        self._loop = None

    async def start(self):
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def _handle(self, reader, writer):
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=5)
            if self.first_line is None:
                self.first_line = line
            if line:
                writer.write(line)
                await writer.drain()
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except (TimeoutError, ConnectionError):
            pass
        finally:
            writer.close()

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()


class _LoopThread:
    """Runs an asyncio loop in a daemon thread; callables scheduled via
    run_coroutine_threadsafe. Lets the (pytest-asyncio) test loop connect to
    loopback servers that live in their own loop."""

    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever,
                                        daemon=True)
        self._thread.start()

    def run(self, coro):
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=10)

    def close(self):
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)


@pytest.fixture
def echo():
    loop = _LoopThread()
    srv = EchoServer()
    loop.run(srv.start())
    yield srv
    loop.run(srv.stop())
    loop.close()


@pytest.fixture
def proxy(monkeypatch, rds):
    monkeypatch.setattr(egress, "EGRESS_FLOOR", True)
    monkeypatch.setattr(egress, "FLOOR_EXEMPT", "")
    loop = _LoopThread()
    p = egress.EgressProxy()
    loop.run(p.start())
    yield p
    loop.run(p.stop())
    loop.close()


async def _exchange(port: int, payload: bytes, *, expect_403: bool = False):
    """Open a socket to the proxy, send payload, return raw response."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(payload)
    await writer.drain()
    chunks = []
    try:
        while True:
            data = await asyncio.wait_for(reader.read(65536), timeout=5)
            if not data:
                break
            chunks.append(data)
    except (TimeoutError, ConnectionError):
        pass
    writer.close()
    return b"".join(chunks)


class TestConnect:
    pytestmark = pytest.mark.asyncio
    async def test_connect_allow_relays(self, proxy, echo):
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
        writer.write(f"CONNECT 127.0.0.1:{echo.port} HTTP/1.1\r\n"
                     f"Host: 127.0.0.1:{echo.port}\r\n\r\n".encode())
        await writer.drain()
        status = await asyncio.wait_for(reader.readline(), timeout=5)
        assert b"200 Connection established" in status
        await reader.readline()  # blank line after the status line
        writer.write(b"ping\n")
        await writer.drain()
        echoed = await asyncio.wait_for(reader.readline(), timeout=5)
        assert echoed == b"ping\n"
        writer.close()

    async def test_connect_denied_imds(self, proxy, rds):
        resp = await _exchange(
            proxy.port,
            b"CONNECT 169.254.169.254:80 HTTP/1.1\r\nHost: 169.254.169.254:80\r\n\r\n")
        assert resp.startswith(b"HTTP/1.1 403")
        assert b"X-Egress-Floor" in resp
        bl = egress.blocks_snapshot()
        assert bl["counters"].get("egress-proxy:floor", 0) == 1

    async def test_connect_denied_rfc1918(self, proxy):
        resp = await _exchange(
            proxy.port,
            b"CONNECT 10.1.2.3:443 HTTP/1.1\r\nHost: 10.1.2.3:443\r\n\r\n")
        assert resp.startswith(b"HTTP/1.1 403")


class TestAbsoluteUri:
    pytestmark = pytest.mark.asyncio
    async def test_absolute_uri_rewritten_to_origin_form(self, proxy, echo):
        payload = (f"GET http://127.0.0.1:{echo.port}/foo?x=1 HTTP/1.1\r\n"
                   f"Host: 127.0.0.1:{echo.port}\r\n\r\n").encode()
        resp = await _exchange(proxy.port, payload)
        # the echo server echoes the request it received — must be origin-form
        assert echo.first_line == b"GET /foo?x=1 HTTP/1.1\r\n"
        assert b"Host: 127.0.0.1" in resp

    async def test_absolute_uri_denied(self, proxy, rds):
        payload = (b"GET http://169.254.169.254/latest/meta-data HTTP/1.1\r\n"
                   b"Host: 169.254.169.254\r\n\r\n")
        resp = await _exchange(proxy.port, payload)
        assert resp.startswith(b"HTTP/1.1 403")
        bl = egress.blocks_snapshot()
        assert bl["counters"].get("egress-proxy:floor", 0) == 1

    async def test_floor_off_passes_everything(self, monkeypatch, proxy):
        monkeypatch.setattr(egress, "EGRESS_FLOOR", False)
        # 127.0.0.2 is loopback but NOT the exempt host — floor off means it
        # is attempted; port 1 refuses instantly → 502 (not a floor 403)
        resp = await _exchange(
            proxy.port,
            b"CONNECT 127.0.0.1:1 HTTP/1.1\r\nHost: 127.0.0.1:1\r\n\r\n")
        assert resp.startswith(b"HTTP/1.1 502")


class TestResidentialChain:
    pytestmark = pytest.mark.asyncio
    async def test_chain_through_residential_when_enabled(self, proxy, echo,
                                                          monkeypatch):
        from search_gateway.extract import proxies
        monkeypatch.setattr(proxies, "PROXY_ENABLED", True)
        monkeypatch.setattr(proxies, "PROXY_GATEWAY", "127.0.0.1:9999")
        monkeypatch.setattr(proxies, "PROXY_PROTOCOL", "http")
        calls: list[tuple] = []

        async def fake_via_gateway(host, port):
            calls.append((host, port))
            return await asyncio.open_connection("127.0.0.1", echo.port)

        monkeypatch.setattr(egress, "_connect_via_gateway", fake_via_gateway)
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
        writer.write(b"CONNECT 8.8.8.8:443 HTTP/1.1\r\nHost: 8.8.8.8:443\r\n\r\n")
        await writer.drain()
        status = await asyncio.wait_for(reader.readline(), timeout=5)
        assert b"200 Connection established" in status
        await reader.readline()  # blank line
        assert calls == [("8.8.8.8", 443)]
        writer.close()

    async def test_direct_when_proxy_disabled(self, proxy, echo, monkeypatch):
        from search_gateway.extract import proxies
        monkeypatch.setattr(proxies, "PROXY_ENABLED", False)
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
        writer.write(f"CONNECT 127.0.0.1:{echo.port} HTTP/1.1\r\n\r\n".encode())
        await writer.drain()
        status = await asyncio.wait_for(reader.readline(), timeout=5)
        assert b"200 Connection established" in status
        await reader.readline()  # blank line
        writer.close()


class _ConnectServer:
    """Loopback server that answers CONNECT with a fixed status line, then
    tunnels raw bytes to a target port (mini residential gateway)."""

    def __init__(self, status: bytes = b"HTTP/1.1 200 Connection established\r\n\r\n"):
        self._server = None
        self.port = 0
        self._status = status
        self._target: tuple[str, int] | None = None
        self.requests: list[bytes] = []

    def target(self, host: str, port: int):
        self._target = (host, port)

    async def start(self):
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def _handle(self, reader, writer):
        try:
            first = await asyncio.wait_for(reader.readline(), timeout=5)
            self.requests.append(first)
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=5)
                self.requests.append(line)
                if line in (b"\r\n", b"\n", b""):
                    break
            writer.write(self._status)
            await writer.drain()
            if self._status.startswith(b"HTTP/1.1 200") and self._target:
                r2, w2 = await asyncio.open_connection(*self._target)
                async def pump(src, dst):
                    try:
                        while True:
                            data = await src.read(65536)
                            if not data:
                                break
                            dst.write(data)
                            await dst.drain()
                    except (ConnectionError, asyncio.CancelledError):
                        pass
                    finally:
                        dst.close()
                await asyncio.gather(pump(reader, w2), pump(r2, writer))
        except (TimeoutError, ConnectionError, OSError):
            pass
        finally:
            writer.close()

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()


@pytest.fixture
def connect_server():
    loop = _LoopThread()
    srv = _ConnectServer()
    loop.run(srv.start())
    yield srv
    loop.run(srv.stop())
    loop.close()


class TestResidentialGateway:
    pytestmark = pytest.mark.asyncio
    async def test_connect_via_gateway_happy_path(self, echo, connect_server,
                                                    monkeypatch):
        connect_server.target("127.0.0.1", echo.port)
        from search_gateway.extract import proxies
        monkeypatch.setattr(proxies, "PROXY_GATEWAY",
                            f"127.0.0.1:{connect_server.port}")
        from search_gateway.extract.egress import _connect_via_gateway
        reader, writer = await _connect_via_gateway("8.8.8.8", 443)
        writer.write(b"ping\n")
        await writer.drain()
        echoed = await asyncio.wait_for(reader.readline(), timeout=5)
        assert echoed == b"ping\n"
        assert connect_server.requests[0].startswith(b"CONNECT 8.8.8.8:443")
        writer.close()

    async def test_connect_via_gateway_rejected(self, connect_server,
                                                  monkeypatch):
        connect_server._status = b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n"
        from search_gateway.extract import proxies
        monkeypatch.setattr(proxies, "PROXY_GATEWAY",
                            f"127.0.0.1:{connect_server.port}")
        from search_gateway.extract.egress import _connect_via_gateway
        with pytest.raises(OSError, match="rejected"):
            await _connect_via_gateway("8.8.8.8", 443)

    async def test_connect_via_gateway_has_auth_header(self, echo, connect_server,
                                                       monkeypatch):
        connect_server.target("127.0.0.1", echo.port)
        from search_gateway.extract import proxies
        monkeypatch.setattr(proxies, "PROXY_GATEWAY",
                            f"127.0.0.1:{connect_server.port}")
        monkeypatch.setattr(proxies, "PROXY_USERNAME", "user-any-sid-x-ttl-30m")
        monkeypatch.setattr(proxies, "PROXY_PASSWORD", "pw")
        from search_gateway.extract.egress import _connect_via_gateway
        await _connect_via_gateway("8.8.8.8", 443)
        # the CONNECT request carried Proxy-Authorization (basic, uri-encoded)
        assert any(b"Proxy-Authorization: Basic" in line
                   for line in connect_server.requests)

    async def test_socks5_protocol_falls_back_direct(self, echo, monkeypatch):
        from search_gateway.extract import egress, proxies
        monkeypatch.setattr(proxies, "PROXY_ENABLED", True)
        monkeypatch.setattr(proxies, "PROXY_PROTOCOL", "socks5")
        monkeypatch.setattr(proxies, "PROXY_GATEWAY", "127.0.0.1:9999")
        p = egress.EgressProxy()
        await p.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", p.port)
        writer.write(f"CONNECT 127.0.0.1:{echo.port} HTTP/1.1\r\n\r\n".encode())
        await writer.drain()
        status = await asyncio.wait_for(reader.readline(), timeout=5)
        assert b"200 Connection established" in status
        await p.stop()
        writer.close()

    async def test_upstream_connect_failure_yields_502(self, proxy):
        # port 1 refuses instantly
        resp = await _exchange(
            proxy.port,
            b"CONNECT 127.0.0.1:1 HTTP/1.1\r\nHost: 127.0.0.1:1\r\n\r\n")
        assert resp.startswith(b"HTTP/1.1 502")

    async def test_absolute_uri_bad_target_closes(self, proxy):
        resp = await _exchange(proxy.port, b"GET not-a-url HTTP/1.1\r\n\r\n")
        assert resp == b""  # connection closed without response

    async def test_absolute_uri_upstream_failure(self, proxy):
        resp = await _exchange(
            proxy.port,
            b"GET http://127.0.0.1:1/ HTTP/1.1\r\nHost: 127.0.0.1:1\r\n\r\n")
        assert resp.startswith(b"HTTP/1.1 502")


class TestRelayClose:
    pytestmark = pytest.mark.asyncio
    async def test_client_close_terminates_relay(self, proxy, echo):
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
        writer.write(f"CONNECT 127.0.0.1:{echo.port} HTTP/1.1\r\n\r\n".encode())
        await writer.drain()
        await asyncio.wait_for(reader.readline(), timeout=5)
        await reader.readline()
        writer.write(b"x\n")
        await writer.drain()
        await asyncio.sleep(0.05)
        writer.close()  # abrupt close — relay must not hang the server loop

    async def test_connect_partial_headers_closes(self, proxy):
        # client sends a CONNECT line then goes away mid-headers
        _reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
        writer.write(b"CONNECT 127.0.0.1:9 HTTP/1.1\r\nHost: ")
        await writer.drain()
        writer.close()
        await asyncio.sleep(0.1)  # proxy must not raise out of its handler


class TestSingleton:
    pytestmark = pytest.mark.asyncio
    async def test_disabled_returns_none(self, monkeypatch):
        monkeypatch.setattr(egress, "EGRESS_PROXY", False)
        monkeypatch.setattr(egress, "_proxy", None)
        assert await egress.get_proxy() is None
        assert egress.proxy_url() is None

    async def test_lazy_start_and_reuse(self, monkeypatch):
        monkeypatch.setattr(egress, "EGRESS_PROXY", True)
        monkeypatch.setattr(egress, "_proxy", None)
        p1 = await egress.get_proxy()
        p2 = await egress.get_proxy()
        assert p1 is p2  # singleton
        assert p1.port > 0
        assert egress.proxy_url() == f"http://127.0.0.1:{p1.port}"
        await p1.stop()
        monkeypatch.setattr(egress, "_proxy", None)


class TestStatusSection:
    pytestmark = pytest.mark.asyncio
    async def test_doctor_egress_section_extended(self, monkeypatch, rds):
        from search_gateway.extract import harden
        monkeypatch.setattr(harden, "table_installed", lambda: False)
        monkeypatch.setattr(harden, "_nft", lambda: None)
        monkeypatch.setattr(egress, "EGRESS_PROXY", True)
        monkeypatch.setattr(egress, "EGRESS_FLOOR", True)
        st = egress.status()
        assert st["proxy"]["enabled"] is True
        assert st["kernel"]["mode"] == "required"
        assert st["kernel"]["installed"] is False
        assert st["floor"]["enabled"] is True
