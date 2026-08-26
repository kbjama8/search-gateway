"""L1 egress floor — the always-blocked network baseline (Phase 7).

Pure IP/hostname matching only. NO DNS in the floor: a hostname that resolves
into a blocked range is invisible here by design — the L3 kernel filter
(`harden.py`) catches what the floor can't see. Fail-closed only on literals.

Checked pre-nav AND post-redirect (LESSONS.md §1.5, hermes-agent PR #21228):
a redirect can jump from a public page to a private/metadata host, so every
hook site checks before navigating and, where the transport exposes the final
URL, after.

Exemption is limited to the gateway's own local infra (SEARXNG_BASE and
REDIS_URL hosts) plus the operator allowlist `KORTEX_SEARCH_FLOOR_EXEMPT`
(comma-separated hostnames/IPs). Nothing else bypasses the floor.

L2 (0.4.2): `EgressProxy` — a loopback CONNECT/absolute-URI proxy that fronts
the anonymous browser tier (D7.2). Every target passes the floor again here
(deny 403 + telemetry); allowed targets chain through the residential tier
when it is enabled. Anonymous engines only — the authenticated OpenCLI tier
keeps L1+L3.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import ipaddress
import logging
from urllib.parse import urlsplit

from ..config import EGRESS_FLOOR, EGRESS_PROXY, FLOOR_EXEMPT, REDIS_URL, SEARXNG_BASE
from ..stats import blocks_snapshot, record_block

logger = logging.getLogger("kortex_search.extract.egress")

# Everything a public-content rekortex search must never egress to:
# loopback, RFC1918, link-local (IMDS lives here), CGNAT, plus the specific
# cloud metadata ranges (ECS 169.254.170.2/23, Alibaba 100.100.100.200 — inside
# CGNAT already, Azure v6 fd00:ec2::254).
ALWAYS_BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("127.0.0.0/8"),      # loopback (plus ::1 below)
    ipaddress.ip_network("10.0.0.0/8"),       # RFC1918
    ipaddress.ip_network("172.16.0.0/12"),    # RFC1918
    ipaddress.ip_network("192.168.0.0/16"),   # RFC1918
    ipaddress.ip_network("169.254.0.0/16"),   # link-local (IMDS: 169.254.169.254)
    ipaddress.ip_network("100.64.0.0/10"),    # CGNAT (Alibaba IMDS: 100.100.100.200)
    ipaddress.ip_network("0.0.0.0/8"),        # unspecified / "this network"
    ipaddress.ip_network("::1/128"),          # loopback v6
    ipaddress.ip_network("::/128"),           # unspecified v6
    ipaddress.ip_network("fe80::/10"),        # link-local v6
    ipaddress.ip_network("fd00:ec2::254/128"),  # Azure IMDS v6
    ipaddress.ip_network("169.254.170.0/23"),   # ECS metadata range (incl. 169.254.170.2/23)
)

# Name-based floor: metadata hostnames and DNS-magic names. The IP literals
# are listed too — a hostile URL can hide the literal in the host (e.g. userinfo
# tricks) and only the name check sees it.
ALWAYS_BLOCKED_HOSTNAMES = frozenset({
    "metadata.google.internal", "metadata", "metadata.azure.internal",
    "169.254.169.254", "169.254.170.2", "169.254.170.23",
    "100.100.100.200", "localhost",
})

_LOCAL_SUFFIXES = (".localhost", ".local")


class EgressBlocked(Exception):
    """The floor rejected this URL (pre-nav or post-redirect)."""

    def __init__(self, url: str, reason: str):
        super().__init__(f"blocked (egress-floor/{reason}): {url}")
        self.url = url
        self.reason = reason


def _host_of_url(url: str) -> str | None:
    """Lowercased, dot-stripped hostname of a URL (None for unparseable)."""
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    return host.rstrip(".").lower()


def _parse_exempt() -> set[str]:
    """Exempt hostnames/IPs: the gateway's own loopback deps + allowlist."""
    out: set[str] = set()
    for url in (SEARXNG_BASE, REDIS_URL):
        host = _host_of_url(url)
        if host:
            out.add(host)
    for item in FLOOR_EXEMPT.split(","):
        item = item.strip().lower()
        if item:
            out.add(item)
    return out


def _is_exempt(host: str) -> bool:
    try:
        return host in _parse_exempt()
    except Exception as exc:  # noqa: BLE001 — exemption parsing never blocks traffic
        logger.debug("exempt parse error: %s", exc)
        return False


def _reason_for(host: str) -> str | None:
    """None = allowed; otherwise a short human reason the hook can surface."""
    if _is_exempt(host):
        return None
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        # not a literal — name-based checks only (no DNS in the floor)
        if host in ALWAYS_BLOCKED_HOSTNAMES:
            return "hostname"
        if host == "localhost" or host.endswith(_LOCAL_SUFFIXES):
            return "local-name"
        return None
    for net in ALWAYS_BLOCKED_NETWORKS:
        if addr.version == net.version and addr in net:
            return str(net)
    return None


def is_always_blocked_url(url: str) -> tuple[bool, str]:
    """Pure floor check: (blocked, reason). No Redis, no DNS, no raising.

    Exemptions apply (local-infra deps + operator allowlist). A non-literal
    hostname that is not on the block list passes — the kernel layer catches
    what the floor can't see.
    """
    host = _host_of_url(url)
    if not host:
        # unparseable URLs are suspect, not blockable — let the transport fail
        return False, ""
    reason = _reason_for(host)
    if reason is None:
        return False, ""
    return True, reason


def check_egress(url: str, source: str | None = None) -> tuple[bool, str]:
    """Floor check + block-event telemetry. (blocked, reason) — never raises."""
    if not EGRESS_FLOOR:
        return False, ""
    blocked, reason = is_always_blocked_url(url)
    if blocked:
        record_block(source or "egress", "floor", reason)
    return blocked, reason


def assert_egress(url: str, source: str | None = None) -> None:
    """Raise EgressBlocked when the floor rejects the URL (all hook sites)."""
    blocked, reason = check_egress(url, source)
    if blocked:
        raise EgressBlocked(url, reason)


def status() -> dict:
    """Doctor section: floor state + denial counters (kernel/proxy fields
    grow in 0.4.2 — shape kept stable across the release split)."""
    bl = blocks_snapshot()
    denied = bl["counters"].get("egress:floor", 0)
    last = bl["recent"][-1] if bl["recent"] else None
    from .harden import status as _harden_status
    harden = _harden_status()
    proxy = _proxy_status()
    return {
        "floor": {"enabled": bool(EGRESS_FLOOR), "denied": denied},
        "proxy": proxy,
        "kernel": {"mode": harden["mode"], "installed": harden["installed"],
                   "covered": harden["covered"]},
        "denied_count": denied,
        "last_denial": last,
    }


def _proxy_status() -> dict:
    if not EGRESS_PROXY:
        return {"enabled": False, "note": "KORTEX_SEARCH_EGRESS_PROXY=0"}
    return {"enabled": True,
            "port": _proxy.port if _proxy is not None else None,
            "note": "L2 forced-proxy for the anonymous tier"}


# --------------------------------------------------------------------------- #
# L2 — EgressProxy: loopback CONNECT/absolute-URI proxy (D7.2)
# --------------------------------------------------------------------------- #

_DENY_BODY = "blocked by kortex-search egress floor"


class EgressProxy:
    """Loopback HTTP proxy fronting the anonymous browser tier.

    The browser is pointed at `127.0.0.1:<port>` with forced-proxy flags
    (`--proxy-server` + `--host-resolver-rules="MAP * 0.0.0.0, EXCLUDE
    127.0.0.1"`, LESSONS.md §1.5) so *every* socket it opens — even after a
    redirect or a DNS rebind — must pass the floor here. Denied targets get a
    403 + block telemetry; allowed targets are relayed directly, or chained
    through the residential tier when `proxies.enabled()`.
    """

    def __init__(self):
        self._server: asyncio.AbstractServer | None = None
        self._port = 0
        self._clients: set[asyncio.Task] = set()

    @property
    def port(self) -> int:
        return self._port

    async def start(self) -> None:
        if self._server is not None:
            return
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self._port = self._server.sockets[0].getsockname()[1]
        logger.info("egress proxy bound to 127.0.0.1:%d", self._port)

    async def stop(self) -> None:
        # cancel client tasks FIRST — wait_closed() would otherwise wait on
        # relay loops that can never see EOF
        for task in list(self._clients):
            task.cancel()
        await asyncio.gather(*self._clients, return_exceptions=True)
        self._clients.clear()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(self, reader: asyncio.StreamReader,
                      writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._clients.add(task)
        try:
            await self._serve(reader, writer)
        finally:
            if task is not None:
                self._clients.discard(task)

    async def _serve(self, reader, writer) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=30)
        except (TimeoutError, ConnectionError):
            writer.close()
            return
        if not line or len(line) > 8192:
            writer.close()
            return
        parts = line.decode("iso-8859-1", "replace").split()
        if len(parts) < 3:
            writer.close()
            return
        method, target, _version = parts[0].upper(), parts[1], parts[2]

        if method == "CONNECT":
            await self._serve_connect(target, reader, writer)
        else:
            await self._serve_absolute(method, target, reader, writer)

    async def _deny(self, writer, reason: str) -> None:
        # telemetry is recorded by check_egress (the single denial event)
        body = _DENY_BODY.encode()
        writer.write(
            f"HTTP/1.1 403 Forbidden\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"X-Egress-Floor: {reason}\r\n"
            f"Connection: close\r\n\r\n".encode() + body)
        await writer.drain()
        writer.close()

    async def _serve_connect(self, target: str, reader, writer) -> None:
        host, _, port_s = target.rpartition(":")
        port = int(port_s) if port_s.isdigit() else 443
        blocked, reason = check_egress(f"https://{host}:{port}",
                                       "egress-proxy")
        if blocked:
            await self._deny(writer, reason)
            return
        try:
            up_reader, up_writer = await self._connect_upstream(host, port)
        except OSError as exc:
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            await writer.drain()
            writer.close()
            logger.debug("egress proxy upstream connect failed: %s", exc)
            return
        # consume + discard the remaining CONNECT headers — they must never
        # leak into the tunnel (the target would read them as its first bytes)
        try:
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=30)
                if line in (b"\r\n", b"\n", b""):
                    break
        except (TimeoutError, asyncio.IncompleteReadError):
            writer.close()
            up_writer.close()
            return
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await writer.drain()
        await _relay(reader, writer, up_reader, up_writer)

    async def _serve_absolute(self, method: str, target: str, reader,
                              writer) -> None:
        # http://host/path absolute-URI form (proxy-style requests)
        try:
            parts = urlsplit(target)
            host = parts.hostname
            port = parts.port or 80
            path = parts.path or "/"
            if parts.query:
                path = f"{path}?{parts.query}"
        except ValueError:
            writer.close()
            return
        if not host:
            writer.close()
            return
        blocked, reason = check_egress(target, "egress-proxy")
        if blocked:
            await self._deny(writer, reason)
            return
        try:
            up_reader, up_writer = await self._connect_upstream(host, port)
        except OSError as exc:
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            await writer.drain()
            writer.close()
            logger.debug("egress proxy upstream connect failed: %s", exc)
            return
        # origin-form inside the tunnel (correct proxy behaviour)
        up_writer.write(f"{method} {path} HTTP/1.1\r\n".encode())
        # forward the rest of the headers verbatim (Host header is re-sent by
        # the client in the absolute-URI form — keep it)
        rest = await reader.readuntil(b"\r\n\r\n")
        up_writer.write(rest)
        await up_writer.drain()
        await _relay(reader, writer, up_reader, up_writer)

    async def _connect_upstream(self, host: str, port: int):
        """Direct or residential-chained upstream connection.

        The residential chain is http-protocol only (CONNECT with
        Proxy-Authorization); socks5 falls back to direct with a warning —
        degrade explicitly, never silently.
        """
        from . import proxies
        if proxies.enabled() and proxies.PROXY_PROTOCOL == "http":
            return await _connect_via_gateway(host, port)
        if proxies.enabled():
            logger.warning("egress proxy: residential chain for %s is "
                           "unsupported (socks5) — connecting directly",
                           proxies.PROXY_PROTOCOL)
        return await asyncio.open_connection(host, port)


async def _connect_via_gateway(host: str, port: int):
    """CONNECT tunnel through the residential gateway (http protocol)."""
    from . import proxies
    gateway = proxies.PROXY_GATEWAY
    if ":" in gateway:
        g_host, _, g_port_s = gateway.rpartition(":")
        g_port = int(g_port_s) if g_port_s.isdigit() else 8080
    else:
        g_host, g_port = gateway, 8080
    reader, writer = await asyncio.open_connection(g_host, g_port)
    user, pw = proxies._credentials()
    token = base64.b64encode(f"{user}:{pw}".encode()).decode()
    req = (f"CONNECT {host}:{port} HTTP/1.1\r\n"
           f"Host: {host}:{port}\r\n"
           f"Proxy-Authorization: Basic {token}\r\n\r\n")
    writer.write(req.encode())
    await writer.drain()
    status_line = await asyncio.wait_for(reader.readline(), timeout=20)
    if b" 200 " not in status_line:
        writer.close()
        raise OSError(f"residential CONNECT rejected: {status_line!r}")
    # consume the remaining proxy response headers
    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=20)
        if line in (b"\r\n", b"\n", b""):
            break
    return reader, writer


async def _relay(reader_a, writer_a, reader_b, writer_b) -> None:
    async def pump(src, dst):
        try:
            while True:
                data = await src.read(65536)
                if not data:
                    break
                dst.write(data)
                await dst.drain()
        except (ConnectionError, asyncio.CancelledError, OSError):
            pass
        finally:
            with contextlib.suppress(OSError):
                dst.close()

    try:
        await asyncio.gather(pump(reader_a, writer_b), pump(reader_b, writer_a))
    finally:
        for w in (writer_a, writer_b):
            with contextlib.suppress(OSError):
                w.close()


# Lazy singleton (D7.2): started on first use by the anonymous tier.
_proxy: EgressProxy | None = None


async def get_proxy() -> EgressProxy | None:
    """The lazy singleton; None when KORTEX_SEARCH_EGRESS_PROXY=0."""
    global _proxy
    if not EGRESS_PROXY:
        return None
    if _proxy is None:
        _proxy = EgressProxy()
        await _proxy.start()
    return _proxy


def proxy_url() -> str | None:
    """`http://127.0.0.1:<port>` for the Camoufox launch flags, or None."""
    if _proxy is None:
        return None
    return f"http://127.0.0.1:{_proxy.port}"
