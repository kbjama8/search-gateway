"""arXiv academic source (free, no key; Atom XML over HTTPS)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from ..extract.http import HttpError, get_text, request
from ..models import Result
from .base import Source, SourceError

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


class ArxivSource(Source):
    name = "arxiv"
    description = "arXiv preprint search + lookup (free, no key)."
    source_type = "paper"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        url = "https://export.arxiv.org/api/query"
        params = {"search_query": f"all:{query}", "start": 0, "max_results": limit}
        try:
            text = await get_text(
                url, source="arxiv", params=params,
                headers={"User-Agent": "search-gateway/0.1"})
            root = ET.fromstring(text)  # noqa: S314 — ET does not resolve external entities; arxiv.org is a fixed trusted host
        except (HttpError, ET.ParseError) as exc:
            raise SourceError(f"arxiv request failed: {exc}") from exc

        return self._parse_entries(root, limit)

    async def get(self, arxiv_id: str) -> Result:
        """Fetch a single paper by arXiv ID (e.g. '2312.10997')."""
        url = "https://export.arxiv.org/api/query"
        try:
            text = await get_text(
                url, source="arxiv", params={"id_list": arxiv_id},
                headers={"User-Agent": "search-gateway/0.1"})
            root = ET.fromstring(text)  # noqa: S314 — ET does not resolve external entities; arxiv.org is a fixed trusted host
        except (HttpError, ET.ParseError) as exc:
            raise SourceError(f"arxiv get failed: {exc}") from exc
        results = self._parse_entries(root, 1)
        if not results:
            raise SourceError(f"arxiv: no paper found for {arxiv_id}")
        return results[0]

    @staticmethod
    def _parse_entries(root: ET.Element, limit: int) -> list[Result]:
        out: list[Result] = []
        for entry in root.findall("atom:entry", _NS):
            title = (entry.findtext("atom:title", "", _NS) or "").strip()
            id_url = (entry.findtext("atom:id", "", _NS) or "")
            arxiv_id = id_url.rsplit("/abs/", 1)[-1].strip() if id_url else ""
            summary = (entry.findtext("atom:summary", "", _NS) or "").strip()
            published = (entry.findtext("atom:published", "", _NS) or "").strip()
            doi = (entry.findtext("arxiv:doi", "", _NS) or "").strip()
            authors = [a.findtext("atom:name", "", _NS) for a in entry.findall("atom:author", _NS)]
            authors = [a for a in authors if a]
            category = (entry.findtext("arxiv:primary_category", "", _NS) or "").strip()
            pdf = next((lnk.get("href", "") for lnk in entry.findall("atom:link", _NS)
                        if lnk.get("title") == "pdf"), "")
            year = published[:4] or None
            out.append(Result(
                title=title,
                url=id_url or (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""),
                snippet=summary[:800],
                source="arxiv",
                engine="arxiv",
                published=published,
                meta={
                    "arxiv_id": arxiv_id,
                    "doi": doi or None,
                    "authors": authors,
                    "year": int(year) if year and year.isdigit() else None,
                    "venue": category or None,
                    "is_oa": True,
                    "pdf_url": pdf or None,
                    "abstract": summary,
                },
            ))
            if len(out) >= limit:
                break
        return out

    async def available(self) -> tuple[bool, str]:
        try:
            r = await request("GET", "https://export.arxiv.org/api/query",
                              source="arxiv",
                              params={"search_query": "all:test", "max_results": 1},
                              headers={"User-Agent": "search-gateway/0.1"},
                              timeout=10.0)
            return r.status_code == 200, f"http {r.status_code}"
        except HttpError as exc:
            return False, str(exc)
