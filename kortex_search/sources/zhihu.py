"""Zhihu source — 知乎 Q&A search via the v4 web API (cookie-gated).

The v4 search API blocks anonymous access with HTTP 401; it requires the
`d_c0` + `z_c0` cookies from a browser session (Zhihu's OAuth is closed to
third parties — LESSONS.md §3.7). Gated by KORTEX_SEARCH_CN_SOURCES; when
enabled but cookie-less, the source degrades with an explicit `auth:` error
the envelope surfaces — never a silent empty result.
"""

from __future__ import annotations

import logging

from ..config import CN_SOURCES, ZHIHU_COOKIE
from ..extract.http import get_json
from ..models import Result
from .base import Source, SourceError

logger = logging.getLogger("kortex_search.sources.zhihu")

_ENDPOINT = "https://www.zhihu.com/api/v4/search_v3"
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/121.0 Safari/537.36")


def _strip_html(text: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", text or "").strip()


class ZhihuSource(Source):
    name = "zhihu"
    description = "Zhihu Q&A search (v4 API; requires ZHIHU_COOKIE)."
    source_type = "forum"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        if not CN_SOURCES:
            raise SourceError(
                "disabled (KORTEX_SEARCH_CN_SOURCES=0) — zhihu is opt-in")
        if not ZHIHU_COOKIE:
            raise SourceError(
                "auth: ZHIHU_COOKIE not set (zhihu blocks anonymous API "
                "access with HTTP 401)")
        params = {
            "t": "general", "q": query, "correction": 1, "offset": 0,
            "limit": min(limit, 20), "lc_idx": 0, "show_all_topics": 0,
        }
        headers = {
            "User-Agent": _UA,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.zhihu.com/search",
            "Cookie": ZHIHU_COOKIE,
            "x-requested-with": "fetch",
        }
        try:
            data = await get_json(_ENDPOINT, source="zhihu", params=params,
                                  headers=headers)
        except Exception as exc:
            raise SourceError(f"zhihu request failed: {exc}") from exc

        results: list[Result] = []
        for item in (data.get("data") or []):
            obj = item.get("object") or {}
            obj_type = obj.get("type") or item.get("type") or ""
            if obj_type not in ("answer", "article", "question"):
                continue
            r = self._to_result(obj, obj_type)
            if r is not None:
                results.append(r)
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _to_result(obj: dict, obj_type: str) -> Result | None:
        if obj_type == "answer":
            question = obj.get("question") or {}
            title = _strip_html(question.get("name") or question.get("title"))
            qid = question.get("id")
            aid = obj.get("id")
            url = obj.get("url") or (f"https://www.zhihu.com/question/{qid}"
                                     f"/answer/{aid}" if qid and aid else "")
            meta = {"zhihu_type": "answer", "question_id": qid}
        elif obj_type == "article":
            title = _strip_html(obj.get("title") or "")
            url = obj.get("url") or ""
            meta = {"zhihu_type": "article"}
        else:  # question
            title = _strip_html(obj.get("title") or "")
            qid = obj.get("id")
            url = obj.get("url") or (f"https://www.zhihu.com/question/{qid}"
                                     if qid else "")
            meta = {"zhihu_type": "question", "question_id": qid,
                    "answer_count": obj.get("answer_count")}
        if not title and not url:
            return None
        excerpt = _strip_html(obj.get("excerpt") or obj.get("content") or "")
        meta.update({
            "author": (obj.get("author") or {}).get("name"),
            "voteup_count": obj.get("voteup_count"),
            "comment_count": obj.get("comment_count"),
        })
        created = obj.get("created_time") or obj.get("created")
        return Result(
            title=title[:140], url=url, snippet=excerpt[:600],
            source="zhihu", engine="zhihu-v4",
            published=f"{created}" if created else None,
            meta=meta,
        )

    async def available(self) -> tuple[bool, str]:
        if not CN_SOURCES:
            return False, "disabled (KORTEX_SEARCH_CN_SOURCES=0)"
        if not ZHIHU_COOKIE:
            return False, "auth: ZHIHU_COOKIE not set"
        try:
            out = await self.search("test", limit=1)
            return True, f"ok ({len(out)} results)"
        except SourceError as exc:
            return False, str(exc)
