"""Reddit source via OpenCLI (browser session)."""

from __future__ import annotations

from ..models import Result
from .base import Source, SourceError, guard_query, parse_json_or_yaml, run_opencli


class RedditSource(Source):
    name = "reddit"
    description = "Reddit search via OpenCLI (browser login)."
    source_type = "forum"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        query = guard_query(query)
        code, out = await run_opencli(
            ["opencli", "reddit", "search", query, "-f", "json"]
        )
        if code != 0:
            raise SourceError(f"reddit failed: {out[:300]}")
        data = parse_json_or_yaml(out)
        if not isinstance(data, list):
            data = data.get("data", data.get("results", [])) if isinstance(data, dict) else []
        results = []
        for p in data[:limit]:
            if not isinstance(p, dict):
                continue
            results.append(Result(
                title=p.get("title", ""),
                url=p.get("url", ""),
                snippet=(p.get("selftext") or "")[:1200],
                source=self.name,
                engine="opencli",
                published=None,
                meta={
                    "subreddit": p.get("subreddit", ""),
                    "author": p.get("author", ""),
                    "score": p.get("score"),
                    "comments": p.get("comments"),
                    "engagement": {"score": p.get("score"), "comments": p.get("comments")},
                },
            ))
        return results

    async def available(self) -> tuple[bool, str]:
        _code, out = await run_opencli(["opencli", "doctor"], timeout=15, retries=0)
        ok = "Extension: connected" in out or "connected" in out
        return ok, out.strip().split("\n")[0] if out else ""
