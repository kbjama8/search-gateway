"""GitHub source — direct REST API (bypasses the broken local `gh` script)."""

from __future__ import annotations

from ..config import GITHUB_TOKEN
from ..extract.http import HttpError, request
from ..models import Result
from .base import Source, SourceError


class GitHubSource(Source):
    name = "github"
    description = "GitHub repo/code search (REST API)."
    source_type = "repo"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        url = "https://api.github.com/search/repositories"
        headers = {"Accept": "application/vnd.github+json"}
        if GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
        try:
            resp = await request("GET", url, source="github",
                                 params={"q": query, "per_page": limit},
                                 headers=headers, timeout=15.0)
            if resp.status_code == 403:
                raise SourceError("github rate-limited (set GITHUB_TOKEN to raise limit)")
            resp.raise_for_status()
            items = resp.json().get("items", [])
        except HttpError as exc:
            raise SourceError(f"github request failed: {exc}") from exc

        results = []
        for it in items:
            results.append(Result(
                title=it.get("full_name", ""),
                url=it.get("html_url", ""),
                snippet=(it.get("description") or "")[:600],
                source=self.name,
                engine="github-api",
                published=it.get("created_at"),
                meta={
                    "stars": it.get("stargazers_count"),
                    "language": it.get("language"),
                    "forks": it.get("forks_count"),
                    "engagement": {"stars": it.get("stargazers_count"),
                                      "forks": it.get("forks_count")},
                },
            ))
        return results

    async def available(self) -> tuple[bool, str]:
        try:
            r = await request("GET", "https://api.github.com/rate_limit",
                              source="github", timeout=8.0)
            return r.status_code == 200, f"http {r.status_code}"
        except HttpError as exc:
            return False, str(exc)
