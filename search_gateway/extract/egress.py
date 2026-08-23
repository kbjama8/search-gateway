"""L1 egress floor — the always-blocked network baseline (Phase 7).

Pure IP/hostname matching only. NO DNS in the floor: a hostname that resolves
into a blocked range is invisible here by design — the L3 kernel filter
(`harden.py`) catches what the floor can't see. Fail-closed only on literals.

Checked pre-nav AND post-redirect (LESSONS.md §1.5, hermes-agent PR #21228):
a redirect can jump from a public page to a private/metadata host, so every
hook site checks before navigating and, where the transport exposes the final
URL, after.

Exemption is limited to the gateway's own local infra (SEARXNG_BASE and
REDIS_URL hosts) plus the operator allowlist `SEARCH_GATEWAY_FLOOR_EXEMPT`
(comma-separated hostnames/IPs). Nothing else bypasses the floor.
"""

from __future__ import annotations

import ipaddress
import logging
from urllib.parse import urlsplit

from ..config import EGRESS_FLOOR, FLOOR_EXEMPT, REDIS_URL, SEARXNG_BASE
from ..stats import blocks_snapshot, record_block

logger = logging.getLogger("search_gateway.extract.egress")

# Everything a public-content research gateway must never egress to:
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
    return {
        "floor": {"enabled": bool(EGRESS_FLOOR), "denied": denied},
        "proxy": {"enabled": False, "note": "L2 forced-proxy lands in 0.4.2"},
        "kernel": {"installed": None, "note": "L3 kernel filter lands in 0.4.2"},
        "denied_count": denied,
        "last_denial": last,
    }
