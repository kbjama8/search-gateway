"""Browser profile farm + health state machine.

Each profile is (platform x persona x purpose) with a persistent user-data
dir, a fingerprint bundle, and an optional proxy binding. Health is tracked
in Redis with the same shape as `stats.py` (24h-window counters), so profile
flakiness can feed weighted-RRF the same way source flakiness already does.

State machine:

    healthy ──failures≥N──▶ cooldown (exp backoff) ──cycles≥C──▶ quarantined
       ▲                       │
       └─────── success ───────┘

Transitions are explicit and logged; a quarantined profile is never auto-
revived (operator action via `doctor`). No profile config files present =
one default profile derived from the persona model — current behavior.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import redis

from ..config import PLATFORM_BLOCK_LIMIT, PROFILE_DIR, PROFILE_HEALTH_TTL, REDIS_URL
from .fingerprints import lint as lint_bundle

logger = logging.getLogger("kortex_search.extract.profiles")

FAIL_THRESHOLD = PLATFORM_BLOCK_LIMIT
QUARANTINE_CYCLES = 3
STATES = ("healthy", "throttled", "cooldown", "quarantined")

_client: redis.Redis | None = None


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(
            REDIS_URL, decode_responses=True,
            socket_connect_timeout=1.0, socket_timeout=2.0,
        )
    return _client


def _keys(name: str) -> tuple[str, str, str]:
    return (f"ks:ph:{name}:state", f"ks:ph:{name}:fails",
            f"ks:ph:{name}:cycles")


@dataclass
class Profile:
    name: str
    platform: str
    persona: str = "kaiser"
    user_data_dir: str = ""
    fingerprint: dict[str, Any] = field(default_factory=dict)
    proxy: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> Profile:
        return cls(
            name=str(d.get("name") or ""),
            platform=str(d.get("platform") or ""),
            persona=str(d.get("persona") or "kaiser"),
            user_data_dir=str(d.get("user_data_dir") or ""),
            fingerprint=d.get("fingerprint") or {},
            proxy=d.get("proxy") or {},
        )


class ProfileStore:
    """Registry of browser profiles; health lives in Redis, defs on disk."""

    def __init__(self, profiles: list[Profile] | None = None):
        self._profiles: dict[str, Profile] = {}
        if profiles:
            for p in profiles:
                self._profiles[p.name] = p
        else:
            self._load_disk()

    def _load_disk(self) -> None:
        base = Path(PROFILE_DIR).expanduser()
        if not base.exists():
            return
        for path in sorted(base.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("profile def unreadable %s: %s", path, exc)
                continue
            if isinstance(data, list):
                for d in data:
                    p = Profile.from_dict(d)
                    if p.name:
                        self._profiles[p.name] = p
            else:
                p = Profile.from_dict(data)
                if p.name:
                    self._profiles[p.name] = p

    def profiles_for(self, platform: str) -> list[Profile]:
        return [p for p in self._profiles.values()
                if p.platform == platform or p.platform == ""]

    def coherence_report(self) -> dict[str, list[str]]:
        return {p.name: lint_bundle(p.fingerprint)
                for p in self._profiles.values() if p.fingerprint}

    def state(self, name: str) -> str:
        try:
            raw = _get_client().get(_keys(name)[0])
        except redis.RedisError as exc:
            logger.debug("profile state read error: %s", exc)
            raw = None
        return raw if raw in STATES else "healthy"

    def fails(self, name: str) -> int:
        try:
            return int(_get_client().get(_keys(name)[1]) or 0)
        except (redis.RedisError, ValueError):
            return 0

    def cycles(self, name: str) -> int:
        try:
            return int(_get_client().get(_keys(name)[2]) or 0)
        except (redis.RedisError, ValueError):
            return 0

    def available(self, name: str) -> bool:
        return self.state(name) in ("healthy", "throttled")

    def report_success(self, name: str) -> None:
        """One clean run: back to healthy, counter reset."""
        try:
            c = _get_client()
            state, fails, cycles = _keys(name)
            c.set(state, "healthy")
            c.delete(fails)
            c.delete(cycles)
        except redis.RedisError as exc:
            logger.debug("profile success write error: %s", exc)

    def report_failure(self, name: str, vendor: str) -> str:
        """Record a failure; returns the new state. Transitions are
        irreversible without a success or operator action."""
        try:
            c = _get_client()
            state_k, fails_k, cycles_k = _keys(name)
            n = c.incr(fails_k)
            c.expire(fails_k, PROFILE_HEALTH_TTL * 6)
            new_state = "healthy"
            if n >= FAIL_THRESHOLD:
                cycles = int(c.get(cycles_k) or 0)
                c.set(state_k, "cooldown")
                # exponential cooldown; TTL self-cleans the state
                ttl = PROFILE_HEALTH_TTL * (2 ** min(cycles, 6))
                c.expire(state_k, ttl)
                c.set(cycles_k, str(cycles + 1))
                c.expire(cycles_k, PROFILE_HEALTH_TTL * 48)
                new_state = "cooldown"
                if cycles + 1 >= QUARANTINE_CYCLES:
                    c.set(state_k, "quarantined")
                    new_state = "quarantined"
                    logger.warning("profile %s quarantined (vendor=%s, "
                                   "fails=%d)", name, vendor, n)
                else:
                    logger.info("profile %s cooling down %ds (vendor=%s)",
                                name, ttl, vendor)
            return new_state
        except redis.RedisError as exc:
            logger.debug("profile failure write error: %s", exc)
            return "healthy"

    def status(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for name in self._profiles:
            out[name] = {"state": self.state(name), "fails": self.fails(name),
                         "cycles": self.cycles(name)}
        return out


store = ProfileStore()


def default_profile(platform: str) -> Profile:
    """The default profile for a platform when no disk defs exist — the
    current single-bridge behavior, made explicit."""
    base = Path(PROFILE_DIR).expanduser() / f"{platform}-{os.environ.get('USER', 'default')}"
    return Profile(name=f"default-{platform}", platform=platform,
                   user_data_dir=str(base))
