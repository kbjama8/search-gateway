#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate matplotlib charts from a research ledger (and optional results.json).

Charts use the diagram-design editorial skin (paper/ink/muted/accent tokens) so
the quantitative charts and the HTML/SVG diagrams read as one visual language.

Produces PNGs into <run-dir>/assets/:
    source_distribution.png   evidence count per source class (always)
    evidence_per_claim.png    evidence items backing each claim (always)
    year_distribution.png     evidence count per publication year (if years exist)
    citation_histogram.png    citation-count histogram (if results.json has data)

Idempotent: a chart is skipped when its PNG already exists and is newer than its
inputs. Pass --force to regenerate regardless.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# diagram-design skin (see the diagram-design skill's references/style-guide.md)
PAPER = "#f5f5f5"     # white-smoke
INK = "#2d3142"       # jet-black
MUTED = "#4f5d75"     # blue-slate
SOFT = "#7a8399"      # sublabels
ACCENT = "#eb6c36"    # atomic-tangerine (focal)
RULE = "#bfc0c0"      # silver hairlines

SERIF = ["DejaVu Serif", "Liberation Serif", "Georgia", "serif"]
SANS = ["DejaVu Sans", "Liberation Sans", "Arial", "sans-serif"]

STYLE = {"figsize": (7, 3.6), "dpi": 110}


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {path}: {exc}")


def _fresh(png: Path, inputs: list[Path]) -> bool:
    """True when the PNG already exists and is newer than every input."""
    if not png.exists():
        return False
    png_mtime = png.stat().st_mtime
    return all(not i.exists() or i.stat().st_mtime <= png_mtime for i in inputs)


def _style(fig, ax, title: str) -> None:
    """Apply the editorial skin: paper bg, ink/muted type, hairline axes."""
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.set_title(title, fontfamily=SERIF, fontsize=13, color=INK,
                 fontweight="normal", pad=12, loc="left")
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("bottom", "left"):
        ax.spines[spine].set_color(RULE)
        ax.spines[spine].set_linewidth(0.8)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.set_ylabel(ax.get_ylabel(), fontfamily=SANS, fontsize=9, color=SOFT)
    ax.grid(axis="y", color=RULE, linewidth=0.5, alpha=0.5)
    ax.set_axisbelow(True)
    for label in ax.get_xticklabels():
        label.set_fontfamily(SANS)
    for label in ax.get_yticklabels():
        label.set_fontfamily(SANS)


def _save(fig, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", facecolor=PAPER)
    plt.close(fig)


def _bars(ax, labels: list[str], values: list[int], focal_idx: int) -> None:
    """Editorial bars: muted fill, accent on the focal bar only."""
    colors = [ACCENT if i == focal_idx else MUTED for i in range(len(values))]
    ax.bar(labels, values, color=colors)


def chart_source_distribution(evidence: list[dict], out: Path) -> None:
    counts = Counter(e.get("source_type") or "unknown" for e in evidence)
    labels = list(counts)
    values = [counts[l] for l in labels]
    focal = max(range(len(values)), key=values.__getitem__) if values else 0
    fig, ax = plt.subplots(**STYLE)
    _bars(ax, labels, values, focal)
    _style(fig, ax, "Evidence per source class")
    _save(fig, out)


def chart_evidence_per_claim(claims: list[dict], out: Path) -> None:
    labels = [c.get("id", "?") for c in claims]
    values = [len(c.get("evidence_ids") or []) for c in claims]
    focal = max(range(len(values)), key=values.__getitem__) if values else 0
    fig, ax = plt.subplots(**STYLE)
    _bars(ax, labels, values, focal)
    _style(fig, ax, "Evidence items per claim")
    _save(fig, out)


def chart_year_distribution(evidence: list[dict], out: Path) -> None:
    years = [e.get("year") for e in evidence if isinstance(e.get("year"), int)]
    if not years:
        return
    counts = Counter(years)
    ys = sorted(counts)
    values = [counts[y] for y in ys]
    focal = max(range(len(values)), key=values.__getitem__)
    fig, ax = plt.subplots(**STYLE)
    _bars(ax, [str(y) for y in ys], values, focal)
    _style(fig, ax, "Evidence by publication year")
    _save(fig, out)


def chart_citation_histogram(results_json: dict, out: Path) -> None:
    counts = [r.get("meta", {}).get("citation_count") for r in results_json.get("results", [])
              if isinstance(r.get("meta", {}).get("citation_count"), int)]
    if not counts:
        return
    fig, ax = plt.subplots(**STYLE)
    ax.hist(counts, bins=min(12, max(3, len(set(counts)))), color=MUTED)
    _style(fig, ax, "Citation-count distribution")
    _save(fig, out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ledger → matplotlib charts (diagram-design skin)")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--results", default="", help="optional results.json for citation histogram")
    ap.add_argument("--force", action="store_true", help="regenerate even if up-to-date")
    args = ap.parse_args(argv)

    run_dir = Path(args.run_dir).expanduser().resolve()
    ledger_path = run_dir / "ledger.json"
    ledger = _load(ledger_path)
    results_path = Path(args.results).expanduser().resolve() if args.results else run_dir / "results.json"
    inputs = [ledger_path]
    if args.results:
        inputs.append(results_path)
    assets = run_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    evidence = ledger.get("evidence", [])
    claims = ledger.get("claims", [])

    jobs = [
        ("source_distribution.png", lambda: chart_source_distribution(evidence, assets / "source_distribution.png")),
        ("evidence_per_claim.png", lambda: chart_evidence_per_claim(claims, assets / "evidence_per_claim.png")),
        ("year_distribution.png", lambda: chart_year_distribution(evidence, assets / "year_distribution.png")),
    ]
    if args.results or results_path.exists():
        results_json = _load(results_path)
        jobs.append(("citation_histogram.png",
                     lambda: chart_citation_histogram(results_json, assets / "citation_histogram.png")))

    for name, fn in jobs:
        png = assets / name
        if not args.force and _fresh(png, inputs):
            print(f"skip assets/{name} (up-to-date)")
            continue
        fn()
        if png.exists():
            print(f"wrote assets/{name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
