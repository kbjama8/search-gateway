#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# Export pipeline: ledger → charts → diagrams → report.md → HTML/PDF/DOCX → zip.
#
#   export.sh --run-dir <dir> [--results <results.json>]
#
# Order:
#   1. make_charts.py      → matplotlib PNG charts (assets/*.png)
#   2. export_diagram.py   → rasterize any diagram-design HTML (assets/*.html)
#                            to .svg + .png (authored beforehand via the
#                            diagram-design skill)
#   3. make_report.py      → report.md (7 sections + visuals + prose markers) + bib
#   4. bundle deliverable/ → report.{md,html,pdf,docx} + assets + ledger → zip
#
# All tools local/free: matplotlib, playwright, pandoc, weasyprint.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR=""
RESULTS=""
FORCE=0

usage() { echo "usage: $0 --run-dir <dir> [--results <results.json>] [--force]" >&2; exit 1; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-dir) RUN_DIR="$2"; shift 2 ;;
    --results) RESULTS="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    *) usage ;;
  esac
done
[ -n "$RUN_DIR" ] || usage

RUN_DIR="$(cd "$RUN_DIR" 2>/dev/null && pwd)"
[ -f "$RUN_DIR/ledger.json" ] || { echo "no ledger.json in $RUN_DIR" >&2; exit 1; }

echo "== generating matplotlib charts =="
CHART_ARGS=(--run-dir "$RUN_DIR")
[ -n "$RESULTS" ] && CHART_ARGS+=(--results "$RESULTS")
[ "$FORCE" = 1 ] && CHART_ARGS+=(--force)
python3 "$SCRIPT_DIR/make_charts.py" "${CHART_ARGS[@]}"

echo "== rasterizing diagram-design HTML =="
if [ -d "$RUN_DIR/assets" ]; then
  htmls=()
  for html in "$RUN_DIR"/assets/*.html; do
    [ -e "$html" ] && htmls+=("$html")
  done
  if [ "${#htmls[@]}" -gt 0 ]; then
    # one Chromium session for all diagrams; skip unchanged outputs unless --force
    DIAG_ARGS=("${htmls[@]}")
    [ "$FORCE" = 1 ] || DIAG_ARGS+=(--skip-existing)
    python3 "$SCRIPT_DIR/export_diagram.py" "${DIAG_ARGS[@]}"
  else
    echo "  (no .html diagrams — skip)"
  fi
else
  echo "  (no assets/ dir — skip)"
fi

echo "== generating report =="
# Only scaffold report.md when absent — the agent authors prose into it
# (make_report.py runs as a separate step), so never overwrite an existing one.
if [ ! -f "$RUN_DIR/report.md" ]; then
  REPORT_ARGS=(--run-dir "$RUN_DIR")
  [ -n "$RESULTS" ] && REPORT_ARGS+=(--results "$RESULTS")
  python3 "$SCRIPT_DIR/make_report.py" "${REPORT_ARGS[@]}"
else
  echo "  (report.md exists — preserving authored prose; run make_report.py to rescaffold)"
fi

echo "== bundling deliverable =="
DELIVERABLE="$RUN_DIR/deliverable"
rm -rf "$DELIVERABLE"
mkdir -p "$DELIVERABLE/assets"
cp "$RUN_DIR/report.md" "$DELIVERABLE/report.md"
[ -f "$RUN_DIR/references.bib" ] && cp "$RUN_DIR/references.bib" "$DELIVERABLE/references.bib" || true
[ -f "$RUN_DIR/ledger.json" ] && cp "$RUN_DIR/ledger.json" "$DELIVERABLE/ledger.json" || true
[ -f "$RUN_DIR/ledger.md" ] && cp "$RUN_DIR/ledger.md" "$DELIVERABLE/ledger.md" || true
[ -d "$RUN_DIR/assets" ] && cp -r "$RUN_DIR/assets/." "$DELIVERABLE/assets/" || true

cd "$DELIVERABLE"

echo "== export HTML =="
if command -v pandoc >/dev/null 2>&1; then
  pandoc report.md -s -o report.html --metadata title="Research Report" \
    --resource-path="." 2>/dev/null || echo "pandoc html failed (continuing)"
else
  echo "pandoc missing — skipping html"
fi

echo "== export PDF =="
if command -v pandoc >/dev/null 2>&1 && python3 -c "import weasyprint" 2>/dev/null; then
  pandoc report.md -s -o report_body.html --metadata title="Research Report" \
    --resource-path="." 2>/dev/null
  python3 -c "
from weasyprint import HTML
HTML(filename='report_body.html', base_url='.').write_pdf('report.pdf')
print('wrote report.pdf')
" 2>/dev/null && rm -f report_body.html || echo "weasyprint pdf failed (continuing)"
else
  echo "pandoc/weasyprint missing — skipping pdf"
fi

echo "== export DOCX =="
if command -v pandoc >/dev/null 2>&1; then
  pandoc report.md -o report.docx --resource-path="." 2>/dev/null \
    || echo "pandoc docx failed (continuing)"
else
  echo "pandoc missing — skipping docx"
fi

echo "== zip bundle =="
cd "$RUN_DIR"
rm -f deliverable.zip
if command -v zip >/dev/null 2>&1; then
  zip -rq deliverable.zip deliverable
  echo "wrote deliverable.zip"
else
  python3 -c "
import shutil, pathlib
shutil.make_archive('deliverable', 'zip', pathlib.Path('deliverable'))
print('wrote deliverable.zip')
"
fi

echo "== done =="
ls -la "$DELIVERABLE"
