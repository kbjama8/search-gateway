"""Reddit source — farm tier (managed Chrome profile over CDP) first,
OpenCLI browser session as fallback.

The farm tier drives old.reddit.com's search page from a persistent logged-in
profile and extracts posts with a small DOM eval — no OpenCLI, no dependency
on the operator's own browser being open (sweep 2026-09-04, ADR-0009).
"""

from __future__ import annotations

from urllib.parse import quote_plus

from ..config import FARM_ENABLED
from ..extract.profiles import default_profile, store
from ..models import Result
from .base import Source, SourceError, guard_query, parse_json_or_yaml, run_opencli, run_profile

_FARM_JS = (
    "Array.from(document.querySelectorAll('div.thing')).slice(0,20)"
    ".map(e=>({title:(e.querySelector('a.title')||{}).textContent||'',"
    "url:(e.querySelector('a.title')||{}).href||'',"
    "subreddit:e.getAttribute('data-subreddit')||'',"
    "score:e.getAttribute('data-score')||null,"
    "author:e.getAttribute('data-author')||'',"
    "comments:e.getAttribute('data-comments-count')||null}))"
)


def _farm_steps(query: str) -> list[list[str]]:
    """One agent-browser argv per step (the CLI takes a single command per
    invocation — chained args silently run only the first)."""
    url = (f"https://old.reddit.com/search?q={quote_plus(query)}"
           "&sort=relevance&t=all")
    return [
        ["open", url],
        ["wait", "4000"],
        ["eval", _FARM_JS],
    ]


def _parse_farm(text: str, limit: int) -> list[Result]:
    data = parse_json_or_yaml(text)
    if not isinstance(data, list):
        return []
    results = []
    for p in data[:limit]:
        if not isinstance(p, dict):
            continue
        results.append(Result(
            title=(p.get("title") or "").strip()[:160],
            url=p.get("url", ""),
            snippet="",
            source="reddit",
            engine="farm-cdp",
            published=None,
            meta={
                "subreddit": p.get("subreddit", ""),
                "author": p.get("author", ""),
                "score": p.get("score"),
                "comments": p.get("comments"),
                "engagement": {"score": p.get("score"),
                               "comments": p.get("comments")},
            },
        ))
    return results


class RedditSource(Source):
    name = "reddit"
    description = "Reddit search via managed profile farm -> OpenCLI."
    source_type = "forum"

    async def search(self, query: str, limit: int = 10) -> list[Result]:
        query = guard_query(query)
        errors: list[str] = []

        # backend 1: managed profile farm (old.reddit over CDP)
        if FARM_ENABLED:
            profiles = [p for p in store.profiles_for("reddit")
                        if store.available(p.name)] or [default_profile("reddit")]
            for prof in profiles[:1]:
                logged_out = False
                try:
                    _last = ""
                    for step in _farm_steps(query):
                        _code, _last = await run_profile(prof, step,
                                                         source="reddit")
                        # old.reddit redirects anonymous browsing to a login
                        # wall — a healthy profile that is merely not logged
                        # in must NOT be counted as a failure (no quarantine)
                        if step[0] == "open" and "/login" in _last \
                                and "reason=" in _last:
                            logged_out = True
                            break
                    if logged_out:
                        errors.append(
                            "farm: profile not logged in — run "
                            "`kortex-search farm login reddit`")
                        continue
                    results = _parse_farm(_last, limit)
                    if results:
                        store.report_success(prof.name)
                        return results
                    errors.append(f"farm empty: {_last[:120]}")
                except SourceError as exc:
                    store.report_failure(prof.name, "farm")
                    errors.append(f"farm error: {exc}")

        # backend 2: opencli (operator's own browser session)
        try:
            code, out = await run_opencli(
                ["opencli", "reddit", "search", query, "-f", "json"]
            )
        except SourceError as exc:
            ctx = f" ({'; '.join(errors)})" if errors else ""
            raise SourceError(f"reddit failed: {exc}{ctx}") from exc
        if code != 0:
            raise SourceError(f"reddit failed: {out[:300]}"
                              + (f" ({'; '.join(errors)})" if errors else ""))
        data = parse_json_or_yaml(out)
        if not isinstance(data, list):
            data = data.get("data", data.get("results", [])) if isinstance(data, dict) else []
        results = []
        for p in data[:limit]:
            if not isinstance(p, dict):
                continue
            results.append(Result(
                title=p.get("title", ""),
                url=p.get("url", ""),
                snippet=(p.get("selftext") or "")[:1200],
                source=self.name,
                engine="opencli",
                published=None,
                meta={
                    "subreddit": p.get("subreddit", ""),
                    "author": p.get("author", ""),
                    "score": p.get("score"),
                    "comments": p.get("comments"),
                    "engagement": {"score": p.get("score"), "comments": p.get("comments")},
                },
            ))
        return results

    async def available(self) -> tuple[bool, str]:
        _code, out = await run_opencli(["opencli", "doctor"], timeout=15, retries=0)
        ok = "Extension: connected" in out or "connected" in out
        return ok, out.strip().split("\n")[0] if out else ""
