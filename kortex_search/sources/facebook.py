"""Facebook source via OpenCLI (browser session)."""

from __future__ import annotations

from ..models import Result
from .base import Source, SourceError, guard_query, parse_json_or_yaml, run_opencli


class FacebookSource(Source):
    name = "facebook"
    description = "Facebook search (people/pages/groups) via OpenCLI."
    source_type = "post"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        query = guard_query(query)
        code, out = await run_opencli(
            ["opencli", "facebook", "search", query, "-f", "json"]
        )
        if code != 0:
            raise SourceError(f"facebook failed: {out[:300]}")
        data = parse_json_or_yaml(out)
        if not isinstance(data, list):
            data = data.get("data", []) if isinstance(data, dict) else []
        results = []
        for p in data[:limit]:
            if not isinstance(p, dict):
                continue
            results.append(Result(
                title=(p.get("title") or p.get("text") or "")[:140],
                url=p.get("url", ""),
                snippet=(p.get("text") or "")[:600],
                source=self.name,
                engine="opencli",
            ))
        return results
