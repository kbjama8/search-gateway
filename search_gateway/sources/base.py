"""Source base class + subprocess helpers (retry + opencli serialization)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from abc import ABC, abstractmethod

from ..config import (
    PER_SOURCE_TIMEOUT,
    RETRY_BACKOFF,
    RETRY_COUNT,
    RETRYABLE_EXIT_CODES,
)
from ..models import Result

logger = logging.getLogger("search_gateway.sources")

# opencli sources share a single browser bridge (one tab lease at a time),
# so their commands must be serialized to avoid contention timeouts.
OPENCLI_LOCK = asyncio.Semaphore(1)

# Subprocess env allowlist: CLI backends get the runtime essentials only.
# Secrets (DEEPSEEK_API_KEY, GITHUB_TOKEN, …) must NOT reach subprocesses —
# unpinned helpers like `uvx mcp-server-linkedin@latest` would otherwise see
# them. Source-specific auth (twitter) is passed explicitly via `env=`.
_ENV_ALLOWLIST = {
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE",
    "TERM", "TMPDIR", "NO_COLOR", "CLICOLOR", "FORCE_COLOR",
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR",
    "UV_CACHE_DIR", "UV_INDEX_URL", "UV_DEFAULT_INDEX", "UV_PYTHON_INSTALL_DIR",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "http_proxy",
    "https_proxy", "no_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE", "OPENCLI_CONFIG",
}


def _subprocess_env(extra: dict | None = None) -> dict:
    """Minimal env for subprocesses: allowlist + explicit extras."""
    env = {k: v for k, v in os.environ.items() if k in _ENV_ALLOWLIST}
    if extra:
        env.update(extra)
    return env


def _sanitize_text(text: str, cap: int = 200) -> str:
    """Strip control characters + cap length for tool-result error text
    (prevents terminal-control injection via subprocess stderr)."""
    cleaned = "".join(ch for ch in (text or "") if ch >= " " or ch in "\n\t")
    return cleaned[:cap]


def guard_query(query: str) -> str:
    """Reject CLI-unsafe queries: a leading '-' would be parsed as a flag by
    twitter-cli/opencli/yt-dlp (option injection). Fail loudly instead."""
    q = query.strip()
    if q.startswith("-"):
        raise SourceError(
            f"query must not start with '-' (CLI flag-injection guard): {q[:80]!r}"
        )
    return q


def normalize_published(value) -> str | None:
    """Normalize a source's date field into a `_parse_date`-friendly string.

    Adapters emit wildly different shapes: ISO strings, epoch seconds
    (v2ex/stackoverflow), bare years (semantic_scholar/crossref). The gateway's
    freshness filter can only read ISO-ish strings, so unnormalized values
    silently defeated it. Rules:
      - falsy → None
      - "YYYY" → "YYYY-01-01"
      - 8 digits → compact date "YYYYMMDD" (already parseable; passthrough)
      - 9-11 digits → epoch seconds (or ms) → ISO with Z
      - anything else → passthrough (best effort; kept by the freshness filter)
    """
    import datetime as _dt
    import re as _re

    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    if _re.fullmatch(r"\d{4}", s):  # bare year
        return f"{s}-01-01"
    if _re.fullmatch(r"\d{8}", s):  # compact date — already parseable
        return s
    if _re.fullmatch(r"\d{9,11}", s):  # epoch seconds (ms unlikely at 11)
        try:
            ts = int(s)
            if ts > 10_000_000_000:  # ms precision — trim
                ts //= 1000
            return _dt.datetime.fromtimestamp(
                ts, tz=_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, OSError, OverflowError):
            return s
    return s


class SourceError(Exception):
    """Raised when a source cannot fulfil a query."""


async def run_cmd(
    cmd: list[str],
    timeout: int = PER_SOURCE_TIMEOUT,
    env: dict | None = None,
    retries: int = RETRY_COUNT,
) -> tuple[int, str]:
    """Run a command, returning (returncode, combined_stdout).

    Retries transient failures (timeouts and `RETRYABLE_EXIT_CODES`) with
    exponential backoff. Non-transient exit codes (auth failures, 404s, …)
    fail immediately — retrying them wastes the fan-out budget. `command not
    found` is not retried.
    """
    full_env = _subprocess_env(env)
    last_err: SourceError | None = None
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
            detail = _sanitize_text(text, 200)
            if RETRYABLE_EXIT_CODES and code not in RETRYABLE_EXIT_CODES:
                # non-transient (auth/404/usage): fail now, don't burn retries
                raise SourceError(f"exit {code}: {' '.join(cmd)}: {detail}")
            last_err = SourceError(f"exit {code}: {' '.join(cmd)}: {detail}")
        except TimeoutError:
            with contextlib.suppress(Exception):  # best-effort kill
                proc.kill()
            last_err = SourceError(f"timeout ({timeout}s): {' '.join(cmd)}")
        except FileNotFoundError:
            raise SourceError(f"command not found: {cmd[0]}") from None
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
                      env: dict | None = None,
                      retries: int = RETRY_COUNT) -> tuple[int, str]:
    """Run an opencli command serialized against other opencli commands."""
    async with OPENCLI_LOCK:
        return await run_cmd(cmd, timeout=timeout, env=env, retries=retries)


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
