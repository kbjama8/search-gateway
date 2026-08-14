# -*- coding: utf-8 -*-
"""YouTube source via yt-dlp (newline-delimited JSON)."""

from __future__ import annotations

import json

from ..models import Result
from .base import Source, SourceError, run_cmd


class YouTubeSource(Source):
    name = "youtube"
    description = "YouTube search (yt-dlp)."
    source_type = "video"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        code, out = await run_cmd([
            "yt-dlp", f"ytsearch{limit}:{query}",
            "--dump-json", "--skip-download", "--no-warnings",
            "--no-playlist", "--flat-playlist",
        ])
        if code != 0:
            raise SourceError(f"yt-dlp failed: {out[:300]}")

        results = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            results.append(Result(
                title=e.get("title", ""),
                url=e.get("webpage_url") or e.get("url", ""),
                snippet=(e.get("description") or "")[:600],
                source=self.name,
                engine="yt-dlp",
                published=e.get("upload_date"),
                meta={
                    "uploader": e.get("uploader") or e.get("channel"),
                    "duration": e.get("duration"),
                    "views": e.get("view_count"),
                    "engagement": {"views": e.get("view_count")},
                },
            ))
            if len(results) >= limit:
                break
        return results

    async def available(self) -> tuple[bool, str]:
        code, out = await run_cmd(["yt-dlp", "--version"], timeout=15)
        return code == 0, out.strip()
