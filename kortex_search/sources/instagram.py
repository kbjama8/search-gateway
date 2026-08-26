"""Instagram source via OpenCLI (browser session)."""

from __future__ import annotations

from ..models import Result
from .base import Source, SourceError, guard_query, parse_json_or_yaml, run_opencli


class InstagramSource(Source):
    name = "instagram"
    description = "Instagram user search via OpenCLI."
    source_type = "post"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        query = guard_query(query)
        code, out = await run_opencli(
            ["opencli", "instagram", "search", query, "-f", "json"]
        )
        if code != 0:
            raise SourceError(f"instagram failed: {out[:300]}")
        data = parse_json_or_yaml(out)
        if not isinstance(data, list):
            data = data.get("data", []) if isinstance(data, dict) else []
        results = []
        for p in data[:limit]:
            if not isinstance(p, dict):
                continue
            name = p.get("name", "")
            username = p.get("username", "")
            results.append(Result(
                title=name or username,
                url=p.get("url") or (f"https://www.instagram.com/{username}" if username else ""),
                snippet=f"@{username}" if username else "",
                source=self.name,
                engine="opencli",
                meta={"username": username, "verified": p.get("verified")},
            ))
        return results
