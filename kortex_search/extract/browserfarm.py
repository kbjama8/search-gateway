"""Managed profile farm — persistent per-profile Chrome instances over CDP.

The browser-backed social tier used to depend on the OpenCLI bridge, which
requires the operator's own browser to be running with the extension loaded;
when it was not, the whole tier was down. The farm replaces that dependency
with self-managed Chrome profiles driven by `agent-browser` (Apache-2.0) —
raw CDP, no Playwright shim. That is the 2026 benchmark's only zero-block
architectural class (see docs/extraction/BROWSER-TIER-2026.md and the sweep
ledger under ~/research_runs/browser-tier-2026-09-03).

P0 spike (2026-09-04) pinned agent-browser 0.27 semantics:

  * `agent-browser --profile <path> ...` launches Chrome with a persistent
    user-data-dir at <path>; cookies survive `close` → reopen;
  * each profile gets its own CDP port (stable for the session lifetime);
  * concurrent profiles run on distinct ports;
  * `state save <path>` exports cookies+storage (login-state snapshots);
  * license Apache-2.0; Chrome-for-Testing is self-managed.

Design:

  * `ensure(profile)` is idempotent per profile: launches once (egress-gated,
    optionally on a virtual display), records the CDP endpoint + last-use in
    Redis so every gateway process shares farm state;
  * `exec_sync(profile, argv)` runs one agent-browser command against the
    profile with a bounded timeout (stdin=DEVNULL — children must never
    inherit the MCP protocol pipe, sweep 2026-09-03);
  * health = CDP `/json/version` reachability;
  * `reap_idle` shuts down profiles idle beyond KORTEX_SEARCH_FARM_IDLE_TTL.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time

import redis

from ..config import (
    FARM_BROWSER_BIN,
    FARM_COMMAND_TIMEOUT,
    FARM_DISPLAY,
    FARM_IDLE_TTL,
    FARM_LAUNCH_TIMEOUT,
    PROFILE_DIR,
    REDIS_URL,
)
from .profiles import Profile

logger = logging.getLogger("kortex_search.extract.browserfarm")

_client: redis.Redis | None = None
_locks: dict[str, asyncio.Lock] = {}


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(
            REDIS_URL, decode_responses=True,
            socket_connect_timeout=1.0, socket_timeout=2.0,
        )
    return _client


def _lock(name: str) -> asyncio.Lock:
    if name not in _locks:
        _locks[name] = asyncio.Lock()
    return _locks[name]


def _keys(name: str) -> tuple[str, str]:
    return f"ks:farm:{name}:cdp", f"ks:farm:{name}:lastuse"


def _base_env() -> dict[str, str]:
    """Minimal subprocess env: essentials + optional virtual display."""
    keep = {"PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL",
            "LC_CTYPE", "XDG_RUNTIME_DIR", "TMPDIR", "DISPLAY", "XAUTHORITY",
            "AGENT_BROWSER_ENCRYPTION_KEY"}
    env = {k: v for k, v in os.environ.items() if k in keep}
    if FARM_DISPLAY:
        env["DISPLAY"] = FARM_DISPLAY
    return env


def _profile_dir(profile: Profile) -> str:
    if profile.user_data_dir:
        return profile.user_data_dir
    base = os.path.expanduser(PROFILE_DIR) or os.path.expanduser(
        "~/.agent-reach/profiles")
    return os.path.join(base, profile.platform or "web",
                        profile.persona or "default", profile.name or "default")


def _registry_get(name: str) -> tuple[str, float]:
    try:
        c = _get_client()
        cdp, lastuse = _keys(name)
        return (c.get(cdp) or "", float(c.get(lastuse) or 0))
    except redis.RedisError as exc:
        logger.debug("farm registry read error: %s", exc)
        return "", 0.0


def _registry_set(name: str, cdp: str, lastuse: float) -> None:
    try:
        c = _get_client()
        cdp_k, use_k = _keys(name)
        c.set(cdp_k, cdp)
        c.set(use_k, str(lastuse))
    except redis.RedisError as exc:
        logger.debug("farm registry write error: %s", exc)


def _registry_delete(name: str) -> None:
    try:
        c = _get_client()
        for k in _keys(name):
            c.delete(k)
    except redis.RedisError as exc:
        logger.debug("farm registry delete error: %s", exc)


def _cmd(base: list[str]) -> list[str]:
    return [FARM_BROWSER_BIN, *base]


def _scoped(argv: list[str], scope_name: str,
            extra_env: dict[str, str] | None = None) -> list[str]:
    """Wrap a browser LAUNCH in a per-profile systemd scope when the L3
    nft filter is installed but the gateway itself is not inside the
    covered cgroup — the browser's sockets must sit under the kernel
    egress rules (same pattern as the OpenCLI tier, D7.1).

    Only the initial launch is scoped: the browser daemon inherits the
    scope cgroup for its whole life, so later agent-browser commands
    (localhost IPC to the daemon) must NOT reuse the scope name — a live
    daemon keeps the transient scope loaded, and systemd-run would refuse
    a second scope with the same name.

    systemd-run transient units do NOT inherit the caller's environment,
    so display/path vars must be forwarded explicitly via --setenv
    (otherwise Chrome fails with "Missing X server or $DISPLAY").
    """
    from . import harden
    try:
        st = harden.status()
    except Exception:  # noqa: BLE001
        return argv
    if st.get("installed") and not st.get("covered"):
        args = ["systemd-run", "--user", "--scope", "--quiet", "--collect",
                "--unit", f"ks-egress-{scope_name}"]
        for k in ("DISPLAY", "XAUTHORITY", "TMPDIR", "XDG_RUNTIME_DIR"):
            v = (extra_env or {}).get(k)
            if v:
                args += [f"--setenv={k}={v}"]
        return [*args, *argv]
    return argv


async def _clean_stale_scope(scope_name: str) -> None:
    """Drop a lingering ks-egress-<name> scope from a dead browser before a
    relaunch (a live daemon would have answered the CDP probe instead)."""
    for argv in (
        ["systemctl", "--user", "stop", f"ks-egress-{scope_name}.scope"],
        ["systemctl", "--user", "reset-failed", f"ks-egress-{scope_name}.scope"],
    ):
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL)
            await asyncio.wait_for(proc.wait(), timeout=15)
        except (TimeoutError, OSError):
            return


async def _spawn(argv: list[str], timeout: float,
                 scope_name: str = "",
                 scope_env: dict[str, str] | None = None) -> tuple[int, str]:
    """Spawn an agent-browser process with DEVNULL stdin (children must
    never inherit the MCP protocol pipe — sweep 2026-09-03)."""
    if scope_name:
        argv = _scoped(argv, scope_name, extra_env=scope_env)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=_base_env(),
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        with contextlib.suppress(Exception):
            proc.kill()
        return -1, f"farm command timed out ({timeout:.0f}s): {argv[1]!r}"
    return proc.returncode or 0, out.decode("utf-8", "replace")


async def ensure(profile: Profile) -> tuple[bool, str]:
    """Launch the profile's browser if it is not already serving CDP.

    Returns (ok, detail). Idempotent per profile: a per-name asyncio lock
    serializes concurrent first-touches; the CDP endpoint is persisted in
    Redis so every gateway process shares one browser per profile.

    Egress discipline: the launch is refused unless the L3 filter is live
    (same gate as the OpenCLI tier — browser children must sit inside the
    kernel egress cgroup).
    """
    from . import harden
    name = profile.name
    async with _lock(name):
        cdp, _ = _registry_get(name)
        if cdp and await _cdp_alive(cdp):
            _touch(name)
            return True, cdp
        pdir = _profile_dir(profile)
        try:
            # installed-check only: _scoped() wraps the launch in a
            # ks-egress-<name> transient scope when the gateway itself is
            # not inside the covered cgroup (same policy as the OpenCLI tier)
            harden.enforce()
        except harden.EgressUnhardened as exc:
            return False, str(exc)
        os.makedirs(pdir, exist_ok=True)
        headed = bool(FARM_DISPLAY)
        argv = _cmd(["--profile", pdir, "open", "about:blank"]
                    + (["--headed"] if headed else []))
        code, out = await _spawn(argv, timeout=FARM_LAUNCH_TIMEOUT,
                                 scope_name=name)
        if code != 0:
            # a stale ks-egress-<name> scope from a dead browser can block
            # the relaunch; clean it and retry once
            if "already loaded" in out or "fragment file" in out:
                await _clean_stale_scope(name)
                code, out = await _spawn(argv, timeout=FARM_LAUNCH_TIMEOUT,
                                         scope_name=name)
            if code != 0:
                return False, f"launch failed: {out[:300]}"
        code2, out2 = await _spawn(
            _cmd(["--profile", pdir, "get", "cdp-url", "--json"]),
            timeout=FARM_LAUNCH_TIMEOUT)
        if code2 != 0:
            return False, f"cdp-url failed: {out2[:300]}"
        cdp = _parse_cdp(out2)
        if not cdp:
            return False, f"cdp-url unparseable: {out2[:300]}"
        _registry_set(name, cdp, time.time())
        return True, cdp


async def _cdp_alive(cdp: str) -> bool:
    """Liveness probe: TCP connect to the CDP port.

    NOT an agent-browser invocation — the CLI auto-launches a browser
    daemon on any command, so a CLI-based probe would resurrect dead
    profiles. A listening port means the daemon is up; subsequent exec
    commands talk to that daemon.
    """
    import re
    m = re.search(r"://127\.0\.0\.1:(\d+)", cdp or "")
    if not m:
        return False
    port = int(m.group(1))
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), timeout=2.0)
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        return True
    except (TimeoutError, OSError):
        return False


def _parse_cdp(out: str) -> str:
    try:
        data = json.loads(out)
        return (data.get("data") or {}).get("cdpUrl") or ""
    except json.JSONDecodeError:
        return ""


def _touch(name: str) -> None:
    _, use_k = _keys(name)
    try:
        _get_client().set(use_k, str(time.time()))
    except redis.RedisError as exc:
        logger.debug("farm touch error: %s", exc)


async def exec_sync(profile: Profile, argv: list[str],
                    timeout: float = FARM_COMMAND_TIMEOUT) -> tuple[int, str]:
    """Run one agent-browser command against the profile's browser."""
    pdir = _profile_dir(profile)
    # daemon IPC (localhost) — the browser already lives in its egress scope
    code, out = await _spawn(_cmd(["--profile", pdir, *argv]),
                             timeout=timeout)
    _touch(profile.name)
    return code, out


async def health(profile: Profile) -> bool:
    cdp, _ = _registry_get(profile.name)
    if not cdp:
        return False
    return await _cdp_alive(cdp)


async def shutdown(profile: Profile) -> None:
    """Close the profile's browser and clear its registry entry."""
    pdir = _profile_dir(profile)
    with contextlib.suppress(Exception):
        await _spawn(_cmd(["--profile", pdir, "close"]), timeout=30)
    _registry_delete(profile.name)


async def shutdown_all(profiles: list[Profile]) -> None:
    for p in profiles:
        await shutdown(p)


async def reap_idle(profiles: list[Profile]) -> list[str]:
    """Shut down profiles idle beyond FARM_IDLE_TTL; returns their names."""
    now = time.time()
    reaped = []
    for p in profiles:
        _, lastuse = _registry_get(p.name)
        if lastuse and now - lastuse > FARM_IDLE_TTL:
            await shutdown(p)
            reaped.append(p.name)
    return reaped


async def status(profiles: list[Profile]) -> dict[str, dict]:
    """Doctor section: per-profile browser state."""
    out: dict[str, dict] = {}
    for p in profiles:
        cdp, lastuse = _registry_get(p.name)
        alive = await _cdp_alive(cdp) if cdp else False
        out[p.name] = {
            "cdp": cdp or None,
            "alive": alive,
            "idle_s": round(time.time() - lastuse) if lastuse else None,
            "user_data_dir": _profile_dir(p),
            "headed": bool(FARM_DISPLAY),
        }
    return out
