"""Twitter/X source — twitter-cli first, managed profile farm second,
opencli fallback (query-time failover)."""

from __future__ import annotations

import os
from urllib.parse import quote_plus

from ..config import FARM_ENABLED
from ..extract.profiles import default_profile, store
from ..extract.vault import env_file_for
from ..models import Result
from .base import Source, SourceError, guard_query, run_cmd, run_opencli, run_profile

_FARM_JS = (
    "JSON.stringify(Array.from(document.querySelectorAll('article')).slice(0,20)"
    ".map(a=>({text:(a.innerText||'').slice(0,300),"
    "href:(a.querySelector('a[href*=\"/status/\"]')||{}).href||'',"
    "author:(a.querySelector('[data-testid=\"User-Name\"]')||{}).innerText||''})))"
)


def _farm_steps(query: str) -> list[list[str]]:
    url = f"https://x.com/search?q={quote_plus(query)}&f=top"
    return [
        ["open", url],
        ["wait", "5000"],
        ["eval", _FARM_JS],
    ]


def _parse_farm(text: str, limit: int) -> list[Result]:
    from .base import parse_json_or_yaml
    data = parse_json_or_yaml(text)
    if not isinstance(data, list):
        return []
    if not isinstance(data, list):
        return []
    results = []
    for t in data[:limit]:
        if not isinstance(t, dict):
            continue
        text = (t.get("text") or "").strip()
        author = (t.get("author") or "").strip().split("\n")[0]
        href = t.get("href") or ""
        url = f"https://x.com{href}" if href.startswith("/") else href
        if not text and not url:
            continue
        results.append(Result(
            title=text[:120],
            url=url,
            snippet=text,
            source="twitter",
            engine="farm-cdp",
            meta={"author": author, "engagement": {}},
        ))
    return results


def _load_twitter_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = env_file_for("twitter")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
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

        # backend 2: managed profile farm (x.com search over CDP)
        if FARM_ENABLED:
            profiles = [p for p in store.profiles_for("twitter")
                        if store.available(p.name)] or [default_profile("twitter")]
            for prof in profiles[:1]:
                try:
                    _last = ""
                    for step in _farm_steps(query):
                        _code, _last = await run_profile(prof, step,
                                                         source="twitter")
                    results = _parse_farm(_last, limit)
                    if results:
                        store.report_success(prof.name)
                        return results
                    errors.append(f"farm empty: {_last[:120]}")
                except SourceError as exc:
                    store.report_failure(prof.name, "farm")
                    errors.append(f"farm error: {exc}")

        # backend 3: opencli (browser session)
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
