# -*- coding: utf-8 -*-
"""LinkedIn source via mcp-server-linkedin (mcporter).

NOTE: the Kaiser Chen LinkedIn account is currently blocked on QR
human-verification, so this source errors until the user completes login
(`uvx mcp-server-linkedin@latest --login --no-headless`).
"""

from __future__ import annotations

import re

from ..models import Result
from .base import Source, SourceError, run_cmd

_FIELD = re.compile(r"^(Name|Headline|Current Position|URL|Profile URL)\s*:\s*(.*)$", re.M)


class LinkedInSource(Source):
    name = "linkedin"
    description = "LinkedIn people search (mcp-server-linkedin)."
    source_type = "post"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        code, out = await run_cmd([
            "mcporter", "call", "linkedin.search_people",
            f"keywords={query}", "--output", "text",
        ])
        if code != 0:
            raise SourceError(f"linkedin failed (blocked?): {out[:200]}")
        return self._parse(out, limit)

    @staticmethod
    def _parse(text: str, limit: int) -> list[Result]:
        results = []
        cur: dict = {}
        for line in text.splitlines():
            m = _FIELD.match(line)
            if m:
                key = m.group(1)
                val = m.group(2).strip()
                if key in ("Name",):
                    if cur and (cur.get("name") or cur.get("url")):
                        results.append(LinkedInSource._make(cur))
                    cur = {"name": val}
                elif key in ("Headline", "Current Position"):
                    cur["headline"] = val
                elif key in ("URL", "Profile URL"):
                    cur["url"] = val
        if cur and (cur.get("name") or cur.get("url")):
            results.append(LinkedInSource._make(cur))
        return results[:limit]

    @staticmethod
    def _make(cur: dict) -> Result:
        name = cur.get("name", "")
        url = cur.get("url", "")
        return Result(
            title=name[:140],
            url=url,
            snippet=(cur.get("headline") or "")[:400],
            source="linkedin",
            engine="mcp-server-linkedin",
        )

    async def available(self) -> tuple[bool, str]:
        _code, out = await run_cmd(["uvx", "mcp-server-linkedin@latest", "--status"], timeout=60)
        ok = "Session is valid" in out
        return ok, out.strip().split("\n")[-1] if out else ""
