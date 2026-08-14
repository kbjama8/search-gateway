#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export diagram-design HTML files to standalone .svg and .png.

Implements the export procedure from the diagram-design skill's `export.md`:
  - SVG: extract the first <svg> node, make it standalone (xmlns, viewBox,
    preserved <title>/<desc>/role/aria), inject Google Fonts @import (XML-safe),
    prepend the XML declaration.
  - PNG: render the ORIGINAL HTML with Playwright and screenshot only the <svg>
    element's bounding box (transparent background, device_scale_factor=2).

All PNGs are rendered in a SINGLE Chromium session (one browser, one page per
file) — much faster than launching Chromium per diagram.

Usage:
    export_diagram.py <a.html> [<b.html> ...] [--scale 2] [--svg-only|--png-only]
                      [--skip-existing]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

GOOGLE_FONTS_CSS = (
    "@import url('https://fonts.googleapis.com/css2?"
    "family=Instrument+Serif:ital@0;1"
    "&amp;family=Geist:wght@400;500;600"
    "&amp;family=Geist+Mono:wght@400;500;600&amp;display=swap');"
)


def extract_svg(src: Path) -> str | None:
    html = src.read_text(encoding="utf-8")
    m = re.search(r"<svg\b.*?</svg>", html, flags=re.DOTALL)
    if not m:
        return None
    svg = m.group(0)
    if "xmlns=" not in svg[:200]:
        svg = re.sub(r"<svg\b", '<svg xmlns="http://www.w3.org/2000/svg"', svg, count=1)
    style = f"<style>{GOOGLE_FONTS_CSS}</style>"
    if "<defs>" in svg:
        svg = svg.replace("<defs>", f"<defs>{style}", 1)
    else:
        svg = re.sub(r"(<svg[^>]*>)", rf"\1<defs>{style}</defs>", svg, count=1)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + svg


def _skip_existing(src: Path, out: Path) -> bool:
    return out.exists() and src.stat().st_mtime <= out.stat().st_mtime


def export_many(html_files: list[Path], scale: float,
                do_svg: bool, do_png: bool, skip_existing: bool) -> None:
    if do_png:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("playwright missing — skipping PNG export", file=sys.stderr)
            do_png = False

    # SVG first (pure regex, no browser).
    if do_svg:
        for src in html_files:
            out = src.with_suffix(".svg")
            if skip_existing and _skip_existing(src, out):
                print(f"skip {out.name} (up-to-date)")
                continue
            svg = extract_svg(src)
            if svg is None:
                print(f"no <svg> block in {src.name} — not a diagram file")
                continue
            out.write_text(svg, encoding="utf-8")
            print(f"wrote {out.name}")

    # PNG in one browser session.
    if do_png:
        todo = []
        for src in html_files:
            out = src.with_suffix(".png")
            if skip_existing and _skip_existing(src, out):
                print(f"skip {out.name} (up-to-date)")
                continue
            todo.append((src, out))
        if not todo:
            return
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(device_scale_factor=scale)
            for src, out in todo:
                page.goto(f"file://{src.resolve().as_posix()}")
                page.wait_for_load_state("networkidle")
                page.locator("svg").first.screenshot(path=str(out), omit_background=True)
                print(f"wrote {out.name}")
            browser.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="export diagram-design HTML → .svg + .png")
    ap.add_argument("src", nargs="+", help="one or more diagram HTML files")
    ap.add_argument("--scale", type=float, default=2.0, help="PNG device_scale_factor (default 2)")
    ap.add_argument("--svg-only", action="store_true")
    ap.add_argument("--png-only", action="store_true")
    ap.add_argument("--skip-existing", action="store_true",
                    help="skip output if already newer than the source HTML")
    args = ap.parse_args(argv)

    html_files = [Path(s).expanduser().resolve() for s in args.src]
    missing = [str(f) for f in html_files if not f.exists()]
    if missing:
        raise SystemExit("not found: " + ", ".join(missing))

    export_many(html_files, args.scale,
                do_svg=not args.png_only,
                do_png=not args.svg_only,
                skip_existing=args.skip_existing)
    return 0


if __name__ == "__main__":
    sys.exit(main())
