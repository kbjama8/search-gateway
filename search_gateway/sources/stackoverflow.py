"""Stack Exchange / Stack Overflow source (free, no key — low-volume)."""

from __future__ import annotations

from ..extract.http import HttpError, get_json, request
from ..models import Result
from .base import Source, SourceError, normalize_published


def epoch_to_published(creation_date) -> str | None:
    """Convert the Stack Exchange epoch-seconds timestamp to a parseable ISO
    string (epoch strings defeat `_parse_date` → freshness duplication + no
    year filtering). Backward-compat alias for the shared contract."""
    return normalize_published(creation_date)


class StackOverflowSource(Source):
    name = "stackoverflow"
    description = "Stack Overflow Q&A search (Stack Exchange API)."
    source_type = "forum"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        url = "https://api.stackexchange.com/2.3/search/advanced"
        params = {
            "order": "desc", "sort": "relevance", "q": query,
            "site": "stackoverflow", "pagesize": limit,
            "filter": "withbody",
        }
        try:
            data = await get_json(url, source="stackoverflow", params=params,
                                  timeout=20.0)
        except HttpError as exc:
            raise SourceError(f"stackoverflow request failed: {exc}") from exc

        results = []
        for it in data.get("items", []):
            results.append(Result(
                title=it.get("title", ""),
                url=it.get("link", ""),
                snippet=self._strip_html(it.get("body", ""))[:800],
                source=self.name,
                engine="stackexchange",
                published=epoch_to_published(it.get("creation_date")),
                meta={
                    "question_id": it.get("question_id"),
                    "accepted": bool(it.get("accepted_answer_id")),
                    "answer_count": it.get("answer_count"),
                    "is_answered": it.get("is_answered"),
                    "author": (it.get("owner") or {}).get("display_name"),
                    "tags": it.get("tags", []),
                    "engagement": {"score": it.get("score"), "views": it.get("view_count")},
                },
            ))
        return results

    @staticmethod
    def _strip_html(text: str) -> str:
        import re
        return re.sub(r"<[^>]+>", " ", text or "")

    async def available(self) -> tuple[bool, str]:
        try:
            r = await request("GET", "https://api.stackexchange.com/2.3/info",
                              source="stackoverflow",
                              params={"site": "stackoverflow"}, timeout=10.0)
            return r.status_code == 200, f"http {r.status_code}"
        except HttpError as exc:
            return False, str(exc)
