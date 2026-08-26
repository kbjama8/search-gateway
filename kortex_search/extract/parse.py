"""Multi-shape parsing — turn platform output of any shape into Result dicts.

Shape priority (cheap → expensive):
  1. structured JSON/YAML
  2. JSON-LD embedded in HTML
  3. CSS selectors (lxml)
  4. regex fallback
  5. LLM-assisted extraction (gated by KORTEX_SEARCH_LLM_PARSE, validated)

All stages emit the canonical `Result` field subset so downstream fusion,
dedup, and re-rank never see platform-specific shapes.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from ..config import LLM_PARSE
from ..models import Result

# Field aliases sources use for the canonical fields. First match wins.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("title", "name", "full_name", "article_title", "question_title",
              "headline"),
    "url": ("url", "html_url", "link", "webpage_url", "landing_page_url",
            "href"),
    "snippet": ("snippet", "content", "description", "selftext", "abstract",
                "excerpt", "summary", "highlights"),
    "published": ("published", "created_at", "upload_date", "publication_date",
                  "created", "publish_time"),
}

_TRUE = ("true", "1", "yes")


def _first(d: dict, keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def canonicalize_results(items: list[Any], *, source: str, engine: str = "",
                         source_type: str = "web") -> list[Result]:
    """Map loose platform dicts onto the canonical Result shape.

    Unknown fields are preserved under `meta` (minus the canonical ones).
    Items that yield neither title nor url are dropped — a result nobody can
    cite is not a result.
    """
    out: list[Result] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        title = str(_first(it, _FIELD_ALIASES["title"]) or "").strip()
        url = str(_first(it, _FIELD_ALIASES["url"]) or "").strip()
        if not title and not url:
            continue
        snippet = str(_first(it, _FIELD_ALIASES["snippet"]) or "").strip()
        published = _first(it, _FIELD_ALIASES["published"])
        canonical = set(_FIELD_ALIASES["title"]) | set(_FIELD_ALIASES["url"]) \
            | set(_FIELD_ALIASES["snippet"]) | set(_FIELD_ALIASES["published"])
        meta = {k: v for k, v in it.items() if k not in canonical}
        meta.setdefault("source_type", source_type)
        out.append(Result(
            title=title, url=url, snippet=snippet, source=source,
            engine=engine or source, published=str(published) if published else None,
            meta=meta,
        ))
    return out


def parse_jsonld(html: str) -> list[dict]:
    """Extract JSON-LD blocks from HTML (<script type="application/ld+json">).

    Returns decoded objects in document order. Malformed blocks are skipped —
    a broken block must not sink the others.
    """
    out: list[dict] = []
    if not html:
        return out
    for m in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.IGNORECASE | re.DOTALL,
    ):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            out.append(data)
        elif isinstance(data, list):
            out.extend(d for d in data if isinstance(d, dict))
    return out


def parse_css(html: str, rules: list[tuple[str, str, str]],
              ) -> list[dict]:
    """Extract records via (css-selector, field, attribute) rules.

    Each rule matches elements; fields with attribute="" read text content.
    Elements are zipped row-wise so parallel lists form records.
    """
    if not html:
        return []
    try:
        from lxml import html as lxml_html
    except ImportError:
        return []
    doc = lxml_html.fromstring(html)
    columns: list[list[str]] = []
    for selector, _field, attr in rules:
        els = doc.cssselect(selector)
        columns.append(
            [(el.get(attr) or "").strip() if attr else
             " ".join(el.text_content().split())
             for el in els]
        )
    if not columns or not columns[0]:
        return []
    n = max(len(c) for c in columns)
    rows = []
    for i in range(n):
        rows.append({
            rules[j][1]: columns[j][i] if i < len(columns[j]) else ""
            for j in range(len(rules))
        })
    return rows


def parse_regex(text: str, patterns: list[tuple[str, str, str]],
                ) -> list[dict]:
    """Extract records via (regex, field, group) rules over flat text."""
    if not text:
        return []
    rows: list[dict] = []
    for pat, field, group in patterns:
        matches = re.findall(pat, text, re.IGNORECASE | re.MULTILINE)
        for i, m in enumerate(matches):
            val = m if isinstance(m, str) else m[int(group) - 1]
            if i >= len(rows):
                rows.append({})
            rows[i][field] = val.strip()
    return rows


async def llm_assist(text: str, hint: str) -> list[dict]:
    """LLM-assisted extraction for degenerate shapes (gated + validated).

    Returns [] unless KORTEX_SEARCH_LLM_PARSE is on and the LLM is available;
    the output is schema-validated, so a hallucinated shape degrades to [].
    """
    if not LLM_PARSE:
        return []
    from .. import llm
    if not llm.available():
        return []
    prompt = (
        "Extract a JSON list of search-result objects from the text below. "
        "Each object must have exactly the keys title, url, snippet, "
        "published. Output ONLY the JSON array, nothing else.\n\n"
        f"Hint: {hint}\n\nText:\n{text[:12000]}"
    )
    try:
        out = await llm.complete([{"role": "user", "content": prompt}],
                                 max_tokens=2000, temperature=0.0,
                                 thinking=False)
    except Exception:  # noqa: BLE001 — parse stage must never raise
        return []
    start, end = out.find("["), out.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        data = json.loads(out[start:end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    valid = []
    for it in data:
        if (isinstance(it, dict)
                and isinstance(it.get("title"), str)
                and isinstance(it.get("url"), str)):
            valid.append({k: it.get(k, "") for k in
                          ("title", "url", "snippet", "published")})
    return valid


async def parse_shapes(text: str, *, source: str, engine: str = "",
                       source_type: str = "web", hint: str = "",
                       css_rules: list[tuple[str, str, str]] | None = None,
                       regex_patterns: list[tuple[str, str, str]] | None = None,
                       json_path: Callable[[dict], list[Any]] | None = None,
                       ) -> list[Result]:
    """Run the full shape ladder and canonicalize whatever any stage found.

    `json_path` maps a parsed JSON/YAML root to the item list (sources differ
    on where their items live); the other stages emit flat item lists.
    """
    items: list[Any] = []

    from ..sources.base import parse_json_or_yaml  # JSON-first, YAML fallback
    data = parse_json_or_yaml(text)
    if data is not None:
        if json_path is not None:
            items = json_path(data) or []
        elif isinstance(data, list):
            items = data
        elif isinstance(data, dict) and isinstance(data.get("items"), list):
            items = data["items"]
        elif isinstance(data, dict) and isinstance(data.get("results"), list):
            items = data["results"]
        elif isinstance(data, dict) and isinstance(data.get("data"), list):
            items = data["data"]

    if not items and "<" in text:
        blocks = parse_jsonld(text)
        if blocks:
            items = blocks

    if not items and css_rules:
        items = parse_css(text, css_rules)

    if not items and regex_patterns:
        items = parse_regex(text, regex_patterns)

    if not items and hint:
        items = await llm_assist(text, hint)

    return canonicalize_results(items, source=source, engine=engine,
                                source_type=source_type)
