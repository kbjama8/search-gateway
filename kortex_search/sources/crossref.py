"""Crossref academic source — DOI metadata + full reference lists (free, no key)."""

from __future__ import annotations

from ..config import MAILTO
from ..extract.http import HttpError, get_json, request
from ..models import Result
from .base import Source, SourceError, normalize_published

_DOI_QUOTE_SAFE = ""  # a DOI path segment is opaque — quote everything


def _quote_doi(doi: str) -> str:
    """Sanitize a user-supplied DOI for use as a URL path segment.

    A DOI like `10.1/../../admin` or one carrying `?`/`#`/spaces would
    otherwise corrupt the request (bug-sweep discovery 2026-08-26)."""
    import urllib.parse
    return urllib.parse.quote(doi.replace("https://doi.org/", "").strip(),
                              safe=_DOI_QUOTE_SAFE)


class CrossrefSource(Source):
    name = "crossref"
    description = "Crossref DOI metadata + references (free, no key)."
    source_type = "paper"

    async def search(self, query: str, limit: int = 10,
                     year_from: int | None = None) -> list[Result]:
        url = "https://api.crossref.org/works"
        params: dict = {"query": query, "rows": limit, "mailto": MAILTO}
        if year_from:
            params["filter"] = f"from-pub-date:{year_from}-01-01"
        try:
            data = await get_json(url, source="crossref", params=params,
                                  timeout=20.0)
        except HttpError as exc:
            raise SourceError(f"crossref request failed: {exc}") from exc

        return [self._to_result(it) for it in data.get("message", {}).get("items", [])
                if (it.get("title") or [""])[0]]

    async def get(self, doi: str) -> Result:
        doi = _quote_doi(doi)
        url = f"https://api.crossref.org/works/{doi}"
        try:
            data = await get_json(url, source="crossref",
                                  params={"mailto": MAILTO}, timeout=20.0)
        except HttpError as exc:
            raise SourceError(f"crossref get failed: {exc}") from exc
        return self._to_result(data.get("message", {}))

    async def references(self, doi: str, limit: int = 20) -> list[Result]:
        """Full reference list for a DOI (Crossref returns structured refs)."""
        doi = _quote_doi(doi)
        url = f"https://api.crossref.org/works/{doi}"
        try:
            data = await get_json(url, source="crossref",
                                  params={"mailto": MAILTO}, timeout=20.0)
        except HttpError as exc:
            raise SourceError(f"crossref references failed: {exc}") from exc

        out: list[Result] = []
        for ref in data.get("message", {}).get("reference", [])[:limit]:
            title = ref.get("article-title") or ref.get("unstructured", "")[:200] or ""
            doi = ref.get("DOI") or ""
            year = ref.get("year")
            authors = []
            if isinstance(ref.get("author"), list):
                authors = [(a.get("given", "") + " " + a.get("family", "")).strip()
                           for a in ref["author"]]
            out.append(Result(
                title=title[:200] or (ref.get("unstructured", "")[:200]),
                url=f"https://doi.org/{doi}" if doi else "",
                snippet=(ref.get("unstructured") or "")[:600],
                source="crossref",
                engine="crossref-reference",
                meta={
                    "doi": doi or None,
                    "authors": [a for a in authors if a],
                    "year": int(year) if year and str(year).isdigit() else None,
                    "venue": ref.get("journal-title") or None,
                    "source_type": "paper",
                },
            ))
        return out

    @staticmethod
    def _to_result(it: dict) -> Result:
        title = (it.get("title") or [""])[0]
        doi = it.get("DOI") or ""
        authors = [(a.get("given", "") + " " + a.get("family", "")).strip()
                   for a in (it.get("author") or [])]
        authors = [a for a in authors if a]
        venue = (it.get("container-title") or [""])[0] or None
        # year from published date fields
        year = None
        for key in ("published-print", "published-online", "issued", "created"):
            dp = (it.get(key) or {}).get("date-parts") or [[None]]
            if dp and dp[0] and dp[0][0]:
                year = dp[0][0]
                break
        return Result(
            title=title,
            url=it.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
            snippet=(it.get("abstract") or "")[:800],
            source="crossref",
            engine="crossref",
            published=normalize_published(year),
            meta={
                "doi": doi or None,
                "authors": authors,
                "year": int(year) if year and str(year).isdigit() else None,
                "venue": venue,
                "publisher": it.get("publisher"),
                "citation_count": it.get("is-referenced-by-count"),
                "is_oa": None,  # Crossref doesn't reliably report OA
                "abstract": it.get("abstract") or None,
            },
        )

    async def available(self) -> tuple[bool, str]:
        try:
            r = await request("GET", "https://api.crossref.org/works",
                              source="crossref",
                              params={"query": "test", "rows": 1, "mailto": MAILTO},
                              timeout=10.0)
            return r.status_code == 200, f"http {r.status_code}"
        except HttpError as exc:
            return False, str(exc)
