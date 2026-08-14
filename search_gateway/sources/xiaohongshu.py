# -*- coding: utf-8 -*-
"""XiaohongShu source via OpenCLI (browser session).

NOTE: the Kaiser Chen persona has not yet authenticated XiaohongShu, so this
source errors gracefully until configured (Cookie-Editor export → xiaohongshu-mcp,
or an OpenCLI XHS browser session).
"""

from __future__ import annotations

from ..models import Result
from .base import Source, SourceError, parse_json_or_yaml, run_opencli


class XiaohongshuSource(Source):
    name = "xiaohongshu"
    description = "XiaohongShu (小红书) search via OpenCLI."
    source_type = "post"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        code, out = await run_opencli(
            ["opencli", "xiaohongshu", "search", query, "-f", "json"]
        )
        if code != 0:
            raise SourceError(f"xiaohongshu failed (not configured?): {out[:200]}")
        data = parse_json_or_yaml(out)
        if not isinstance(data, list):
            data = data.get("data", []) if isinstance(data, dict) else []
        results = []
        for p in data[:limit]:
            if not isinstance(p, dict):
                continue
            title = p.get("title") or p.get("desc") or ""
            results.append(Result(
                title=title[:140],
                url=p.get("url", ""),
                snippet=(p.get("desc") or p.get("content") or "")[:600],
                source=self.name,
                engine="opencli",
                meta={"author": p.get("author") or p.get("user", {}).get("nickname", "")},
            ))
        return results
