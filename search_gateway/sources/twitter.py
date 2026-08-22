"""Twitter/X source — twitter-cli first, opencli fallback (query-time failover)."""

from __future__ import annotations

import os

from ..config import TWITTER_ENV_FILE
from ..models import Result
from .base import Source, guard_query, run_cmd, run_opencli


def _load_twitter_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if os.path.exists(TWITTER_ENV_FILE):
        with open(TWITTER_ENV_FILE, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                k = k.removeprefix("export ")
                v = v.strip().strip('"').strip("'")
                if k in ("TWITTER_AUTH_TOKEN", "TWITTER_CT0") and v:
                    env[k] = v
    return env


class TwitterSource(Source):
    name = "twitter"
    description = "Twitter/X search (twitter-cli -> opencli)."
    source_type = "post"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        query = guard_query(query)
        errors: list[str] = []

        # backend 1: twitter-cli (needs explicit auth env)
        try:
            env = _load_twitter_env()
            if env.get("TWITTER_AUTH_TOKEN") and env.get("TWITTER_CT0"):
                _code, out = await run_cmd(
                    ["twitter", "search", query, "-n", str(limit), "--json"],
                    env=env,
                )
                results = self._parse_twitter_cli(out)
                if results:
                    return results
                errors.append(f"twitter-cli empty/failed: {out[:120]}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"twitter-cli error: {exc}")

        # backend 2: opencli (browser session)
        try:
            _code, out = await run_opencli(
                ["opencli", "twitter", "search", query, "-f", "json"]
            )
            results = self._parse_opencli(out)
            if results:
                return results
            errors.append(f"opencli empty/failed: {out[:120]}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"opencli error: {exc}")

        if errors:
            from .base import SourceError
            raise SourceError("; ".join(errors))
        return []

    @staticmethod
    def _parse_twitter_cli(text: str) -> list[Result]:
        from .base import parse_json_or_yaml
        data = parse_json_or_yaml(text)
        if not isinstance(data, dict) or not data.get("ok"):
            return []
        tweets = data.get("data", [])
        results = []
        for t in tweets or []:
            if not isinstance(t, dict):
                continue
            author = t.get("author") or t.get("screenName") or t.get("username", "")
            tid = t.get("id", "")
            text = (t.get("text") or "").strip()
            url = t.get("url") or (f"https://x.com/{author}/status/{tid}" if author and tid else "")
            results.append(Result(
                title=text[:120],
                url=url,
                snippet=text,
                source="twitter",
                engine="twitter-cli",
                published=t.get("created_at"),
                meta={"author": author, "likes": t.get("likes"), "views": t.get("views"),
                      "engagement": {"likes": t.get("likes"), "views": t.get("views")}},
            ))
        return results

    @staticmethod
    def _parse_opencli(text: str) -> list[Result]:
        from .base import parse_json_or_yaml
        data = parse_json_or_yaml(text)
        if not isinstance(data, list):
            return []
        results = []
        for t in data:
            if not isinstance(t, dict):
                continue
            author = t.get("author", "")
            tid = t.get("id", "")
            text = (t.get("text") or "").strip()
            url = t.get("url") or (f"https://x.com/{author}/status/{tid}" if author and tid else "")
            results.append(Result(
                title=text[:120],
                url=url,
                snippet=text,
                source="twitter",
                engine="opencli",
                published=t.get("created_at"),
                meta={"author": author, "likes": t.get("likes"), "views": t.get("views"),
                      "engagement": {"likes": t.get("likes"), "views": t.get("views")}},
            ))
        return results
