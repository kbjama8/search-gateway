#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Turn a completed deep-research ledger (+ optional final ranked results) into
a structured, cited `report.md` and a `references.bib`.

Inputs:
    --run-dir   directory containing ledger.json (from research_ledger.py)
    --results   optional path to a results.json (final ranked search_* output
                from the gateway) used to enrich the bibliography with
                authors / venue / citation_count / is_oa / pdf_url.

Outputs (written into --run-dir, or --out-dir if given):
    report.md          the source-of-truth structured report (7 sections)
    references.bib     BibTeX for every evidence item with a citable identity

Stdlib-only. If results.json is absent or a result can't be matched, the
bibliography falls back to the ledger's title/url/year/doi fields.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CONFIDENCE_ORDER = {"high": 0, "med": 1, "low": 2}


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {path}: {exc}")


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "", (text or "")).lower()


def _bibtex_key(authors: list[str] | None, year, title: str) -> str:
    """Build a BibTeX key: lastnameYear, falling back to title-word+year."""
    if authors:
        last = authors[0].strip().split()[-1]
        key = f"{_slug(last)}{year or ''}"
        if key:
            return key
    first_word = re.split(r"[^a-zA-Z0-9]+", (title or "").strip())[:1]
    word = (first_word[0] if first_word else "ref").lower()
    return f"{word}{year or ''}" or f"ref"


def _bibtex_type(source_type: str, venue) -> str:
    if source_type == "paper":
        return "article"
    if source_type in ("repo", "code"):
        return "misc"
    if source_type == "web":
        return "misc"
    return "misc"


def _escape_bib(s: str) -> str:
    return (s or "").replace("&", r"\&").replace("_", r"\_").replace("%", r"\%")


def build_result_index(results_json: dict) -> dict:
    """Index results by doi/arxiv_id/url for bibliography enrichment."""
    index: dict[str, dict] = {}
    for r in results_json.get("results", []):
        m = r.get("meta") or {}
        title = r.get("title", "")
        url = r.get("url", "")
        for key in ("doi", "arxiv_id"):
            if m.get(key):
                index[f"{key}:{m[key]}"] = r
        if url:
            index[f"url:{url}"] = r
        if title:
            index[f"title:{title.lower()}"] = r
    return index


def enrich(ev: dict, index: dict) -> dict:
    """Attach authors/venue/citation_count/is_oa/pdf_url from a matched result."""
    out = dict(ev)
    candidates = []
    if ev.get("doi"):
        candidates.append(index.get(f"doi:{ev['doi']}"))
    if ev.get("arxiv_id"):
        candidates.append(index.get(f"arxiv_id:{ev['arxiv_id']}"))
    if ev.get("url"):
        candidates.append(index.get(f"url:{ev['url']}"))
    title = ev.get("title", "")
    if title:
        candidates.append(index.get(f"title:{title.lower()}"))
    for c in candidates:
        if not c:
            continue
        m = c.get("meta") or {}
        out["authors"] = m.get("authors") or ev.get("authors")
        out["venue"] = m.get("venue") or ev.get("venue")
        out["citation_count"] = m.get("citation_count") if m.get("citation_count") is not None else ev.get("citation_count")
        out["is_oa"] = m.get("is_oa") if m.get("is_oa") is not None else ev.get("is_oa")
        out["pdf_url"] = m.get("pdf_url") or ev.get("pdf_url")
        break
    return out


def _uncertainty(claim: dict, evidence: list[dict]) -> str:
    stances = {e.get("stance") for e in evidence if e.get("claim_id") == claim.get("id")}
    if claim.get("stance_summary") == "contested":
        return "contested"
    if len(evidence) == 1:
        return "single-source"
    if "contradicts" in stances:
        return "contested"
    return "none"


def _evidence_titles(ev_ids: list[str], evidence_by_id: dict) -> list[str]:
    out = []
    for eid in ev_ids:
        e = evidence_by_id.get(eid)
        if not e:
            continue
        ident = e.get("doi") or e.get("arxiv_id") or e.get("year")
        label = e.get("title") or "(untitled)"
        if ident:
            label = f"{label} ({ident})"
        out.append(label)
    return out


def _image(assets_dir: Path, name: str, caption: str) -> str:
    p = assets_dir / name
    if not p.exists():
        return ""
    return f"![{caption}](assets/{name})"


# diagram-design editorial diagrams (HTML authored via the diagram-design skill,
# rasterized to PNG by export_diagram.py). The .svg is kept for vector export.
DIAGRAMS = [
    ("method.png", "Research method"),
    ("claim-graph.png", "Claim → evidence → source graph"),
    ("timeline.png", "Evidence timeline"),
    ("aspect-tree.png", "Aspect map"),
]

# matplotlib quantitative charts (make_charts.py).
CHARTS = [
    ("source_distribution.png", "Evidence per source class"),
    ("evidence_per_claim.png", "Evidence items per claim"),
    ("year_distribution.png", "Evidence by publication year"),
    ("citation_histogram.png", "Citation-count distribution"),
]


def _visualizations(assets_dir: Path) -> list[str]:
    """Collect available diagrams + charts into a Visualizations block."""
    blocks: list[str] = []
    for name, caption in DIAGRAMS:
        img = _image(assets_dir, name, caption)
        if img:
            blocks.append(f"**{caption}**")
            blocks.append("")
            blocks.append(img)
            blocks.append("")
    for name, caption in CHARTS:
        img = _image(assets_dir, name, caption)
        if img:
            blocks.append(f"**{caption}**")
            blocks.append("")
            blocks.append(img)
            blocks.append("")
    return blocks


def render_report(ledger: dict, results_json: dict, assets_dir: Path) -> str:
    claims = ledger.get("claims", [])
    evidence = ledger.get("evidence", [])
    hops = ledger.get("hops", [])
    counter = ledger.get("counter_evidence", [])
    evidence_by_id = {e.get("id"): e for e in evidence}

    index = build_result_index(results_json)
    enriched = [enrich(e, index) for e in evidence]

    question = ledger.get("question", "Untitled research")
    effort = ledger.get("effort", "standard")
    deliverable = ledger.get("deliverable", "evidence-backed research report")
    aspects = ledger.get("aspects", [])
    source_classes = sorted({e.get("source_type") for e in evidence if e.get("source_type")})
    tools = sorted({h.get("tool") for h in hops if h.get("tool")})
    modes = sorted({h.get("mode") for h in hops if h.get("mode")})

    L: list[str] = []
    L.append(f"# {question}")
    L.append("")

    # 1. Executive summary
    L.append("## Executive summary")
    L.append("")
    L.append("<!-- PROSE: rewrite the executive summary in the voice-card register "
             "(see references/voice-card.md), citing [E#]. Keep it ≤1 page. "
             "The scaffolded facts below are reference data, not prose. -->")
    L.append("")
    top = sorted(claims, key=lambda c: (CONFIDENCE_ORDER.get(c.get("confidence"), 3), -(len(c.get("evidence_ids") or []))))
    L.append(f"This report answers **{question}**. It was produced at `{effort}` effort "
             f"across {len(hops)} hops and {len(evidence)} evidence items "
             f"({', '.join(source_classes) or 'none'} source classes).")
    L.append("")
    if top:
        L.append("Top claims:")
        for c in top[:5]:
            evs = ", ".join(c.get("evidence_ids") or []) or "—"
            L.append(f"- **{c.get('id')}** ({c.get('confidence')}, {c.get('stance_summary')}): "
                     f"{c.get('text')} — evidence {evs}")
    if counter:
        L.append(f"- {len(counter)} claim(s) have recorded counter-evidence.")
    L.append("")

    # 2. Research question, scope, methodology
    L.append("## Research question, scope, and methodology")
    L.append("")
    L.append(f"- **Question:** {question}")
    L.append(f"- **Deliverable:** {deliverable}")
    L.append(f"- **Effort level:** {effort}")
    L.append(f"- **Aspects mapped:** {', '.join(aspects) if aspects else '(none recorded)'}")
    L.append(f"- **Paths / tools used:** {', '.join(tools) if tools else '(none recorded)'}")
    L.append(f"- **Hop modes:** {', '.join(modes) if modes else '(none recorded)'}")
    L.append("- **Method:** Frame → Map → Seed → Extract → Verify → Synthesize.")
    L.append("")

    # 3. Evidence table
    L.append("## Evidence table")
    L.append("")
    L.append("| claim | evidence IDs | confidence | stance | key sources |")
    L.append("|-------|--------------|------------|--------|-------------|")
    for c in claims:
        evs = ", ".join(c.get("evidence_ids") or []) or "—"
        titles = _evidence_titles(c.get("evidence_ids") or [], evidence_by_id)
        src = "; ".join(titles[:3]) if titles else "—"
        L.append(f"| {c.get('id')}: {c.get('text','')} | {evs} | {c.get('confidence')} "
                 f"| {c.get('stance_summary')} | {src} |")
    if not claims:
        L.append("| _(no claims)_ | | | | |")
    L.append("")

    # 4. Key findings
    L.append("## Key findings")
    L.append("")
    L.append("<!-- PROSE: turn each finding below into an argument in the voice-card "
             "register — a thesis, the evidence that supports or contests it [E#], "
             "and an edge. The structured data under each heading stays as the "
             "auditable spine. -->")
    L.append("")
    if not claims:
        L.append("_(no claims recorded)_")
    for i, c in enumerate(claims, 1):
        ev_ids = c.get("evidence_ids") or []
        unc = _uncertainty(c, evidence)
        L.append(f"### {i}. {c.get('text')}")
        L.append("")
        L.append(f"- **Claim:** {c.get('id')}")
        L.append(f"- **Evidence:** {', '.join(ev_ids) if ev_ids else 'none'}")
        L.append(f"- **Confidence:** {c.get('confidence')}")
        L.append(f"- **Stance:** {c.get('stance_summary')}")
        L.append(f"- **Uncertainty:** {unc}")
        for eid in ev_ids:
            e = evidence_by_id.get(eid)
            if e:
                L.append(f"  - {e.get('title')} — `{e.get('quote_or_locator')}` "
                         f"[{e.get('stance')}, q{e.get('quality_score')}]")
        L.append("")

    # 5. Counter-evidence and limitations
    L.append("## Counter-evidence and limitations")
    L.append("")
    if counter:
        for ce in counter:
            L.append(f"- **claim {ce.get('claim_id')}**: {ce.get('text')} "
                     f"_(evidence {', '.join(ce.get('evidence_ids') or [])})_")
    else:
        L.append("_(no counter-evidence recorded — a red-team pass may be pending.)_")
    L.append("")

    # 6. Recommendations / next actions
    L.append("## Recommendations / next actions")
    L.append("")
    L.append("<!-- PROSE: write recommendations in the voice-card register — opinionated, "
             "evidence-anchored, with a concrete next action each. The list below is "
             "raw input, not prose. -->")
    L.append("")
    nexts = [h.get("next_questions") for h in hops
             if h.get("next_questions") and h.get("next_questions").strip().lower() not in ("none", "-", "n/a")]
    if nexts:
        for n in nexts:
            L.append(f"- {n}")
    else:
        L.append("- _(none recorded)_")
    L.append("")

    # Visualizations (diagram-design diagrams + matplotlib charts)
    L.append("## Visualizations")
    L.append("")
    for block in _visualizations(assets_dir):
        L.append(block)

    # 7. Bibliography
    L.append("## Bibliography")
    L.append("")
    L.append("See `references.bib` for machine-readable entries.")
    L.append("")
    for e in enriched:
        parts = []
        if e.get("authors"):
            parts.append("; ".join(e["authors"][:6]))
        if e.get("year"):
            parts.append(str(e["year"]))
        if e.get("venue"):
            parts.append(e["venue"])
        meta = ", ".join(parts)
        L.append(f"- {e.get('title')}" + (f" ({meta})" if meta else ""))
        L.append(f"  - URL: {e.get('url')}")
        extra = []
        if e.get("doi"):
            extra.append(f"DOI {e['doi']}")
        if e.get("arxiv_id"):
            extra.append(f"arXiv {e['arxiv_id']}")
        if e.get("citation_count") is not None:
            extra.append(f"{e['citation_count']} citations")
        if e.get("is_oa") is True:
            extra.append("open access")
        if e.get("pdf_url"):
            extra.append(f"PDF {e['pdf_url']}")
        if extra:
            L.append(f"  - {', '.join(extra)}")
    if not enriched:
        L.append("_(no evidence recorded)_")
    L.append("")
    return "\n".join(L)


def render_bib(enriched: list[dict]) -> str:
    lines: list[str] = []
    seen_keys: set[str] = set()
    for e in enriched:
        doi = e.get("doi")
        if not doi and not e.get("arxiv_id") and not e.get("url"):
            continue
        key = _bibtex_key(e.get("authors"), e.get("year"), e.get("title"))
        base_key = key
        n = 2
        while key in seen_keys:
            key = f"{base_key}{n}"
            n += 1
        seen_keys.add(key)
        btype = _bibtex_type(e.get("source_type", "web"), e.get("venue"))
        lines.append(f"@{btype}{{{key},")
        lines.append(f"  title = {{{_escape_bib(e.get('title',''))}}},")
        if e.get("authors"):
            authors = " and ".join(e["authors"][:10])
            lines.append(f"  author = {{{_escape_bib(authors)}}},")
        if e.get("year"):
            lines.append(f"  year = {{{e.get('year')}}},")
        if e.get("venue"):
            lines.append(f"  journal = {{{_escape_bib(e.get('venue'))}}},")
        if doi:
            lines.append(f"  doi = {{{doi}}},")
        if e.get("url"):
            lines.append(f"  url = {{{e.get('url')}}},")
        if e.get("arxiv_id") and not doi:
            lines.append(f"  note = {{arXiv: {e.get('arxiv_id')}}},")
        lines.append("}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ledger.json + results.json → report.md + references.bib")
    ap.add_argument("--run-dir", required=True, help="directory containing ledger.json")
    ap.add_argument("--results", default="", help="optional results.json (final ranked search output)")
    ap.add_argument("--out-dir", default="", help="output dir (default: run-dir)")
    args = ap.parse_args(argv)

    run_dir = Path(args.run_dir).expanduser().resolve()
    ledger = load_json(run_dir / "ledger.json")
    if not ledger:
        raise SystemExit(f"no ledger.json in {run_dir}; run research_ledger.py init first")

    results_json: dict = {}
    if args.results:
        results_json = load_json(Path(args.results).expanduser().resolve())

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else run_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    report_md = render_report(ledger, results_json, run_dir / "assets")
    (out_dir / "report.md").write_text(report_md, encoding="utf-8")

    evidence = ledger.get("evidence", [])
    index = build_result_index(results_json)
    enriched = [enrich(e, index) for e in evidence]
    bib = render_bib(enriched)
    (out_dir / "references.bib").write_text(bib, encoding="utf-8")

    print(f"wrote {out_dir / 'report.md'}")
    print(f"wrote {out_dir / 'references.bib'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
