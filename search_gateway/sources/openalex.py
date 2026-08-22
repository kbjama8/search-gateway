"""OpenAlex academic source — the primary rich scholarly source (free, no key)."""

from __future__ import annotations

import httpx

from ..config import MAILTO
from ..models import Result
from .base import Source, SourceError


def _reconstruct_abstract(inv: dict | None) -> str:
    """Reconstruct abstract text from OpenAlex's abstract_inverted_index."""
    if not inv:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort(key=lambda x: x[0])
    return " ".join(w for _, w in positions)


class OpenAlexSource(Source):
    name = "openalex"
    description = "OpenAlex scholarly works search + citations (free, no key)."
    source_type = "paper"

    async def search(self, query: str, limit: int = 10,
                     year_from: int | None = None,
                     open_access_only: bool = False) -> list[Result]:
        url = "https://api.openalex.org/works"
        params: dict = {"search": query, "per-page": limit, "mailto": MAILTO}
        filters = []
        if year_from:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if open_access_only:
            filters.append("is_oa:true")
        if filters:
            params["filter"] = ",".join(filters)
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise SourceError(f"openalex request failed: {exc}") from exc

        return [r for r in map(self._to_result, data.get("results", [])) if r.title]

    async def get(self, identifier: str) -> Result:
        """Resolve a DOI, arXiv DOI, or OpenAlex ID to a full Result."""
        lookup = identifier
        if identifier.startswith(("10.", "https://doi.org/")):
            doi = identifier.replace("https://doi.org/", "").strip()
            lookup = f"doi:{doi}"
        url = f"https://api.openalex.org/works/{lookup}"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(url, params={"mailto": MAILTO})
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise SourceError(f"openalex get failed: {exc}") from exc
        return self._to_result(data)

    async def citations(self, identifier: str, limit: int = 20) -> list[Result]:
        """Works that cite the given paper (OpenAlex ID, DOI, or arXiv DOI)."""
        wid = await self._resolve_work_id(identifier)
        url = "https://api.openalex.org/works"
        params = {"filter": f"cites:{wid}", "per-page": limit, "mailto": MAILTO}
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise SourceError(f"openalex citations failed: {exc}") from exc
        return [self._to_result(w) for w in data.get("results", [])]

    async def references(self, identifier: str, limit: int = 20) -> list[Result]:
        """References for a paper — resolves OpenAlex `referenced_works` IDs."""
        wid = await self._resolve_work_id(identifier)
        url = f"https://api.openalex.org/works/{wid}"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(url, params={"mailto": MAILTO})
                resp.raise_for_status()
                ref_ids = (resp.json().get("referenced_works") or [])[:limit]
        except httpx.HTTPError as exc:
            raise SourceError(f"openalex references failed: {exc}") from exc
        if not ref_ids:
            return []
        short = [rid.rsplit("/", 1)[-1] for rid in ref_ids]
        url = "https://api.openalex.org/works"
        params = {"filter": f"ids.openalex:{'|'.join(short)}", "per-page": limit, "mailto": MAILTO}
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise SourceError(f"openalex references batch failed: {exc}") from exc
        return [self._to_result(w) for w in data.get("results", [])]

    async def _resolve_work_id(self, identifier: str) -> str:
        """Resolve a DOI / arXiv DOI / OpenAlex ID to the OpenAlex W… ID."""
        s = identifier.strip()
        if s.startswith("W") and s[1:].isdigit():
            return s
        if s.startswith("10."):
            lookup = f"doi:{s.replace('https://doi.org/', '')}"
        else:
            arx = s.replace("arXiv:", "").replace("arxiv:", "").strip()
            lookup = f"doi:10.48550/arxiv.{arx}"
        url = f"https://api.openalex.org/works/{lookup}"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(url, params={"mailto": MAILTO})
                resp.raise_for_status()
                return (resp.json().get("id") or "").rsplit("/", 1)[-1]
        except httpx.HTTPError as exc:
            raise SourceError(f"openalex id resolve failed: {exc}") from exc

    @staticmethod
    def _to_result(w: dict) -> Result:
        doi = (w.get("doi") or "").replace("https://doi.org/", "")
        pid = (w.get("id") or "").rsplit("/", 1)[-1]
        authors = [a.get("author", {}).get("display_name", "")
                   for a in (w.get("authorships") or [])]
        authors = [a for a in authors if a]
        pl = w.get("primary_location") or {}
        venue = (pl.get("source") or {}).get("display_name") if pl.get("source") else None
        oa = w.get("open_access") or {}
        return Result(
            title=w.get("title") or "",
            url=pl.get("landing_page_url") or (f"https://doi.org/{doi}" if doi else ""),
            snippet=_reconstruct_abstract(w.get("abstract_inverted_index"))[:800],
            source="openalex",
            engine="openalex",
            published=w.get("publication_date"),
            meta={
                "doi": doi or None,
                "paper_id": pid or None,
                "authors": authors,
                "year": w.get("publication_year"),
                "venue": venue,
                "citation_count": w.get("cited_by_count"),
                "is_oa": oa.get("is_oa", False),
                "pdf_url": oa.get("oa_url"),
                "abstract": _reconstruct_abstract(w.get("abstract_inverted_index")),
            },
        )

    async def available(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get("https://api.openalex.org/works",
                                     params={"search": "test", "per-page": 1, "mailto": MAILTO})
                return r.status_code == 200, f"http {r.status_code}"
        except httpx.HTTPError as exc:
            return False, str(exc)
