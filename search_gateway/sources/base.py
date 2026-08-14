# -*- coding: utf-8 -*-
"""Source base class + subprocess helpers (retry + opencli serialization)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Optional

from ..config import PER_SOURCE_TIMEOUT, RETRY_BACKOFF, RETRY_COUNT
from ..models import Result

logger = logging.getLogger("search_gateway.sources")

# opencli sources share a single browser bridge (one tab lease at a time),
# so their commands must be serialized to avoid contention timeouts.
OPENCLI_LOCK = asyncio.Semaphore(1)


class SourceError(Exception):
    """Raised when a source cannot fulfil a query."""


async def run_cmd(
    cmd: list[str],
    timeout: int = PER_SOURCE_TIMEOUT,
    env: Optional[dict] = None,
    retries: int = RETRY_COUNT,
) -> tuple[int, str]:
    """Run a command, returning (returncode, combined_stdout).

    Retries transient failures (timeouts and non-zero exits) with exponential
    backoff. `command not found` is not retried.
    """
    full_env = dict(os.environ)
    if env:
        full_env.update(env)

    last_err: Optional[SourceError] = None
    for attempt in range(retries + 1):
        if attempt > 0:
            await asyncio.sleep(RETRY_BACKOFF * (2 ** (attempt - 1)))
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=full_env,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            code = proc.returncode or 0
            text = out.decode("utf-8", "replace")
            if code == 0:
                return code, text
            last_err = SourceError(f"exit {code}: {' '.join(cmd)}: {text[:200]}")
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
            last_err = SourceError(f"timeout ({timeout}s): {' '.join(cmd)}")
        except FileNotFoundError:
            raise SourceError(f"command not found: {cmd[0]}")
    raise last_err  # type: ignore[misc]


def parse_json_or_yaml(text: str):
    """Parse JSON first, then YAML (some CLIs emit one or the other)."""
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    import yaml  # local import: optional
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return None


async def run_opencli(cmd: list[str], timeout: int = PER_SOURCE_TIMEOUT,
                      env: Optional[dict] = None) -> tuple[int, str]:
    """Run an opencli command serialized against other opencli commands."""
    async with OPENCLI_LOCK:
        return await run_cmd(cmd, timeout=timeout, env=env)


class Source(ABC):
    """A pluggable search backend."""

    name: str = ""
    description: str = ""
    source_type: str = "web"  # paper|post|video|repo|web|forum|news|doc|code

    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> list[Result]:
        """Return ranked results for query (best first)."""

    async def available(self) -> tuple[bool, str]:
        """Quick health probe (command/endpoint present)."""
        return True, ""

    def _result(self, title: str, url: str, snippet: str = "", engine: str = "",
                **meta) -> Result:
        meta.setdefault("source_type", self.source_type)
        return Result(title=title or "", url=url or "", snippet=snippet or "",
                      source=self.name, engine=engine, meta=meta)
