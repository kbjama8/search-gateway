"""Exa neural web-search source (via mcporter MCP)."""

from __future__ import annotations

import re

from ..models import Result
from .base import Source, SourceError, guard_query, run_cmd

_BLOCK_SPLIT = re.compile(r"\n---+\n")
_FIELD = re.compile(r"^(Title|URL|Published|Author|Highlights)\s*:\s*(.*)$", re.MULTILINE)


class ExaSource(Source):
    name = "exa"
    description = "Exa neural (semantic) web search via mcporter."

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        query = guard_query(query)
        code, out = await run_cmd([
            "mcporter", "call", "exa.web_search_exa",
            f"query={query}", f"numResults={limit}",
            "--output", "text",
        ])
        if code != 0:
            raise SourceError(f"exa failed: {out[:300]}")
        return self._parse(out, limit)

    @staticmethod
    def _parse(text: str, limit: int) -> list[Result]:
        results: list[Result] = []
        for block in _BLOCK_SPLIT.split(text):
            block = block.strip()
            if not block or "Title:" not in block:
                continue
            fields: dict[str, str] = {}
            for m in _FIELD.finditer(block):
                fields[m.group(1)] = m.group(2).strip()
            title = fields.get("Title", "")
            url = fields.get("URL", "")
            if not title and not url:
                continue
            published = fields.get("Published", "")
            if published in ("N/A", "", "None"):
                published = None
            results.append(Result(
                title=title,
                url=url,
                snippet=(fields.get("Highlights", "") or "")[:1200],
                source="exa",
                engine="exa",
                published=published,
                meta={"author": fields.get("Author", "")},
            ))
            if len(results) >= limit:
                break
        return results

    async def available(self) -> tuple[bool, str]:
        code, out = await run_cmd(["mcporter", "--version"], timeout=10, retries=0)
        return code == 0, out.strip()
