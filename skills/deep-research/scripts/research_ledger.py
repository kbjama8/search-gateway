#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Versioned evidence ledger for the deep-research skill (stdlib-only).

This script performs NO retrieval. It maintains a single JSON ledger
(`ledger.json`, schema v1) that the agent fills in as it drives the
kortex-search MCP tools (`search_*`, `get_paper`, `get_citations`,
`get_references`, `read_url`). It is intentionally auditable, portable, and
runs on Python's standard library alone.

Commands:
    init          create a run directory + empty ledger.json
    add-hop       record one retrieval/inspection hop
    add-claim     register a claim
    add-evidence  attach evidence to a claim
    status        hop budget vs actual, source-class coverage, open claims
    lint          validate the ledger (≥1 evidence per claim, source-id +
                  locator on every evidence, no orphan hops, red-team pass)
    export        emit a human-readable ledger.md next to ledger.json

The ledger is JSON because it is the authoritative artifact; `ledger.md` is a
generated export, never the source of truth.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

SCHEMA_VERSION = 1

# Effort → (hop target, minimum source-class coverage). Hop targets are
# PLANNING TARGETS, not quotas — the lint/readiness gate is the real stop
# condition, and `lint` treats "below target" as a warning, not an error.
EFFORT_DEFAULTS = {
    "quick":       {"hop_target": 4,  "source_classes": 1},
    "standard":    {"hop_target": 8,  "source_classes": 3},
    "deep":        {"hop_target": 14, "source_classes": 4},
    "exhaustive":  {"hop_target": 20, "source_classes": 5},
}

# source_type vocabulary mirrors the gateway's Result.meta `source_type`.
SOURCE_TYPES = ["paper", "post", "forum", "web", "video", "repo",
                "news", "doc", "code"]

HOP_MODES = ["seed", "extract", "verify", "contradict", "synthesize"]

STANCES = ["supports", "contradicts", "context", "weak"]
CONFIDENCES = ["high", "med", "low"]

# Redact anything that looks like a credential before it can hit the ledger.
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|private[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{12,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
]


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(text: str, limit: int = 60) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (slug or "research-run")[:limit].strip("-") or "research-run"


def read_ledger(run_dir: Path) -> dict:
    path = run_dir / "ledger.json"
    if not path.exists():
        raise SystemExit(f"missing ledger.json in {run_dir}; run init first")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ledger.json is not valid JSON: {exc}")
    if data.get("schema") != SCHEMA_VERSION:
        raise SystemExit(
            f"unsupported ledger schema {data.get('schema')!r} (expected {SCHEMA_VERSION})")
    return data


def write_ledger(run_dir: Path, data: dict) -> None:
    data = _normalize(data)
    path = run_dir / "ledger.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _normalize(data: dict) -> dict:
    """Ensure schema fields exist and derived fields are consistent."""
    data.setdefault("schema", SCHEMA_VERSION)
    data.setdefault("run_id", uuid.uuid4().hex)
    data.setdefault("question", "")
    data.setdefault("effort", "standard")
    data.setdefault("deliverable", "")
    data.setdefault("created_at", now_utc())
    data.setdefault("aspects", [])
    data.setdefault("claims", [])
    data.setdefault("evidence", [])
    data.setdefault("hops", [])
    # counter_evidence is DERIVED from evidence with stance="contradicts";
    # recompute so the file is always self-consistent.
    data["counter_evidence"] = _derive_counter_evidence(data)
    return data


def _derive_counter_evidence(data: dict) -> list[dict]:
    by_claim: dict[str, list[dict]] = {}
    for ev in data.get("evidence", []):
        if ev.get("stance") == "contradicts":
            by_claim.setdefault(ev.get("claim_id") or "", []).append(ev)
    out = []
    for claim_id, evs in sorted(by_claim.items()):
        out.append({
            "claim_id": claim_id,
            "text": " / ".join((e.get("quote_or_locator") or e.get("title") or "")
                               for e in evs),
            "evidence_ids": [e.get("id") for e in evs if e.get("id")],
        })
    return out


def _next_id(items: list[dict], prefix: str, key: str = "id") -> str:
    highest = 0
    for it in items:
        m = re.match(rf"^{re.escape(prefix)}(\d+)$", str(it.get(key) or ""))
        if m:
            highest = max(highest, int(m.group(1)))
    return f"{prefix}{highest + 1}"


def _effort_targets(effort: str) -> dict:
    return dict(EFFORT_DEFAULTS.get(effort, EFFORT_DEFAULTS["standard"]))


def maybe_redact(text: str) -> str:
    for pat in SECRET_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


def contains_secret(text: str) -> bool:
    return any(pat.search(text or "") for pat in SECRET_PATTERNS)


# --- commands ---------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    base = Path(args.out_dir).expanduser().resolve()
    run_dir = base / f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{slugify(args.question)}"

    if run_dir.exists() and any(run_dir.iterdir()):
        if not args.force:
            raise SystemExit(f"run directory already exists and is not empty: {run_dir}; use --force to reset it")
        import shutil
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    effort = args.effort
    aspects = [a.strip() for a in (args.aspects or "").split(",") if a.strip()]

    ledger = {
        "schema": SCHEMA_VERSION,
        "run_id": uuid.uuid4().hex,
        "question": args.question,
        "effort": effort,
        "deliverable": args.deliverable or "evidence-backed research report",
        "created_at": now_utc(),
        "aspects": aspects,
        "claims": [],
        "evidence": [],
        "hops": [],
        "counter_evidence": [],
    }
    write_ledger(run_dir, ledger)
    print(str(run_dir))
    return 0


def cmd_add_hop(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    data = read_ledger(run_dir)

    hop = int(args.hop)
    if hop < 1:
        raise SystemExit("--hop must be >= 1")
    if any(h.get("n") == hop for h in data["hops"]):
        raise SystemExit(f"hop already exists: {hop}")

    hop_entry = {
        "n": hop,
        "mode": args.mode,
        "tool": args.tool_or_source,
        "query": args.query_or_action,
        "result_summary": args.result_summary or "",
        "next_questions": args.next_questions or "",
    }
    data["hops"].append(hop_entry)
    write_ledger(run_dir, data)
    print(f"recorded hop {hop}")
    return 0


def cmd_add_claim(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    data = read_ledger(run_dir)

    text = maybe_redact(args.text)
    claim_id = args.id or _next_id(data["claims"], "C")
    if any(c.get("id") == claim_id for c in data["claims"]):
        raise SystemExit(f"claim id already exists: {claim_id}")

    data["claims"].append({
        "id": claim_id,
        "text": text,
        "confidence": args.confidence,
        "stance_summary": "unresolved",
        "agreement": "unresolved",
        "agreement_score": 0,
        "independent_sources": 0,
        "confidence_derived": args.confidence,
        "evidence_ids": [],
    })
    write_ledger(run_dir, data)
    print(f"recorded claim {claim_id}")
    return 0


def cmd_add_evidence(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    data = read_ledger(run_dir)

    hop = int(args.hop)
    if not any(h.get("n") == hop for h in data["hops"]):
        raise SystemExit(f"evidence references missing hop: {hop}; record the hop first")

    if args.claim_id:
        claim = next((c for c in data["claims"] if c.get("id") == args.claim_id), None)
        if claim is None:
            raise SystemExit(f"claim_id does not exist: {args.claim_id}; run add-claim first")
        # link evidence → claim
        if args.claim_id not in claim["evidence_ids"]:
            claim["evidence_ids"].append(args.claim_id)

    evidence_id = args.id or _next_id(data["evidence"], "E")
    if any(e.get("id") == evidence_id for e in data["evidence"]):
        raise SystemExit(f"evidence id already exists: {evidence_id}")

    entry = {
        "id": evidence_id,
        "claim_id": args.claim_id or "",
        "hop": hop,
        "source_id": args.source_id,
        "title": maybe_redact(args.title),
        "url": args.url,
        "source_type": args.source_type,
        "doi": args.doi or None,
        "arxiv_id": args.arxiv_id or None,
        "year": args.year,
        "quality_score": int(args.quality_score),
        "stance": args.stance,
        "quote_or_locator": args.quote_or_locator or "",
        "confidence": args.confidence or "med",
    }
    data["evidence"].append(entry)

    # recompute claim stance_summary
    _refresh_claim_stances(data)
    write_ledger(run_dir, data)
    print(f"recorded evidence {evidence_id}")
    return 0


def _ev_quality(ev: dict) -> int:
    try:
        return int(ev.get("quality_score") or 0)
    except (TypeError, ValueError):
        return 0


def _source_family(ev: dict) -> str:
    """Independence key: DOI > arXiv ID > URL host > source_id.

    Two evidence items sharing a family key are NOT independent corroboration
    (e.g. the same paper recorded via different source_ids).
    """
    if ev.get("doi"):
        return f"doi:{ev['doi']}"
    if ev.get("arxiv_id"):
        return f"arxiv:{ev['arxiv_id']}"
    url = ev.get("url") or ""
    try:
        net = urlparse(url).netloc.lower().lstrip("www.")
    except ValueError:
        net = ""
    if net:
        return f"host:{net}"
    return f"src:{ev.get('source_id') or '?'}"


_CONF_TIER = {"high": 2, "med": 1, "low": 0}
_TIER_CONF = {2: "high", 1: "med", 0: "low"}


def _promote(conf: str) -> str:
    return _TIER_CONF[min(2, _CONF_TIER.get(conf, 1) + 1)]


def _demote(conf: str) -> str:
    return _TIER_CONF[max(0, _CONF_TIER.get(conf, 1) - 1)]


def _refresh_claim_stances(data: dict) -> None:
    for claim in data.get("claims", []):
        evs = [e for e in data.get("evidence", []) if e.get("claim_id") == claim.get("id")]
        claim["evidence_ids"] = [e["id"] for e in evs if e.get("id")]
        stances = {e.get("stance") for e in evs}
        if not evs:
            claim["stance_summary"] = "unresolved"
        elif "contradicts" in stances:
            claim["stance_summary"] = "contested"
        elif "supports" in stances:
            claim["stance_summary"] = "supported"
        else:
            claim["stance_summary"] = "unresolved"

        # Claim-level quality scoring: agreement across independent evidence.
        base_conf = claim.get("confidence", "med")
        contradicts = [e for e in evs if e.get("stance") == "contradicts"]
        strong = [e for e in evs if e.get("stance") == "supports" and _ev_quality(e) >= 4]
        weak = [e for e in evs if e.get("stance") in ("supports", "weak") and _ev_quality(e) < 4]
        n_ind = len({_source_family(e) for e in strong})

        if not evs:
            agreement, score, conf = "unresolved", 0, base_conf
        elif contradicts:
            # any contradiction demotes, regardless of how much support remains
            agreement, score, conf = "contested", n_ind, _demote(base_conf)
        elif n_ind >= 2:
            agreement, score, conf = "corroborated", n_ind, _promote(base_conf)
        elif n_ind == 1:
            agreement, score, conf = "supported", 1, base_conf
        elif weak:
            agreement, score, conf = "weak", 0, _demote(base_conf)
        else:
            agreement, score, conf = "unresolved", 0, base_conf

        claim["agreement"] = agreement
        claim["agreement_score"] = score
        claim["independent_sources"] = n_ind
        claim["confidence_derived"] = conf


def cmd_status(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    data = read_ledger(run_dir)
    targets = _effort_targets(data.get("effort", "standard"))
    hop_target = targets["hop_target"]

    source_types = sorted({e.get("source_type") for e in data["evidence"] if e.get("source_type")})
    open_claims = [c for c in data["claims"] if not c.get("evidence_ids")]
    supported = [c for c in data["claims"] if c.get("stance_summary") == "supported"]
    contested = [c for c in data["claims"] if c.get("stance_summary") == "contested"]
    corroborated = [c for c in data["claims"] if c.get("agreement") == "corroborated"]
    weak = [c for c in data["claims"] if c.get("agreement") == "weak"]

    out = {
        "question": data.get("question"),
        "effort": data.get("effort"),
        "hop_count": len(data["hops"]),
        "hop_target": hop_target,
        "hops_remaining": max(0, hop_target - len(data["hops"])),
        "evidence_count": len(data["evidence"]),
        "claim_count": len(data["claims"]),
        "supported_claims": len(supported),
        "contested_claims": len(contested),
        "corroborated_claims": len(corroborated),
        "weak_claims": len(weak),
        "open_claims": [c.get("id") for c in open_claims],
        "claim_scores": [
            {"id": c.get("id"), "agreement": c.get("agreement", "unresolved"),
             "confidence_derived": c.get("confidence_derived", c.get("confidence")),
             "agreement_score": c.get("agreement_score", 0)}
            for c in data["claims"]
        ],
        "source_classes": source_types,
        "source_class_target": targets["source_classes"],
        "counter_evidence_count": len(data.get("counter_evidence", [])),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    data = read_ledger(run_dir)
    targets = _effort_targets(data.get("effort", "standard"))
    hop_target = targets["hop_target"]
    class_target = targets["source_classes"]

    errors: list[str] = []
    warnings: list[str] = []

    claims = data.get("claims", [])
    evidence = data.get("evidence", [])
    hops = data.get("hops", [])

    hop_numbers = {h.get("n") for h in hops}
    claim_ids = {c.get("id") for c in claims}
    evidence_ids: set[str] = set()

    # hops: no duplicates, valid modes
    seen_hops: set[int] = set()
    for h in hops:
        n = h.get("n")
        if n in seen_hops:
            errors.append(f"duplicate hop number: {n}")
        seen_hops.add(n)
        if h.get("mode") not in HOP_MODES:
            errors.append(f"hop {n} has invalid mode: {h.get('mode')!r}")
        for field in ("tool", "query"):
            if not h.get(field):
                warnings.append(f"hop {n} missing {field}")

    # claims: every claim has ≥1 evidence (hard error — this is the lint gate)
    for c in claims:
        cid = c.get("id")
        if cid not in claim_ids:
            continue
        if c.get("confidence") not in CONFIDENCES:
            errors.append(f"claim {cid} has invalid confidence: {c.get('confidence')!r}")
        if not c.get("evidence_ids"):
            errors.append(f"claim {cid} has no evidence (run add-evidence)")
        # claim-level quality: high-confidence but single-source is fragile
        if c.get("confidence") == "high" and c.get("agreement") in ("supported", "weak"):
            warnings.append(
                f"claim {cid} is {c.get('agreement')} with only "
                f"{c.get('independent_sources', 0)} independent strong source(s) "
                f"yet marked high-confidence — consider a contradiction query or demote")
    if not claims:
        warnings.append("no claims recorded")

    # evidence: source-id + locator required, valid references, no secrets
    for e in evidence:
        eid = e.get("id", "?")
        if eid in evidence_ids:
            errors.append(f"duplicate evidence id: {eid}")
        evidence_ids.add(eid)

        if not e.get("source_id"):
            errors.append(f"evidence {eid} missing source_id")
        if not e.get("quote_or_locator"):
            errors.append(f"evidence {eid} missing quote_or_locator")
        if not e.get("title"):
            errors.append(f"evidence {eid} missing title")
        if not e.get("url"):
            errors.append(f"evidence {eid} missing url")
        if e.get("source_type") not in SOURCE_TYPES:
            errors.append(f"evidence {eid} has invalid source_type: {e.get('source_type')!r}")
        if e.get("stance") not in STANCES:
            errors.append(f"evidence {eid} has invalid stance: {e.get('stance')!r}")
        if e.get("confidence") not in CONFIDENCES:
            errors.append(f"evidence {eid} has invalid confidence: {e.get('confidence')!r}")
        try:
            q = int(e.get("quality_score", 0))
            if q not in (1, 2, 3, 4, 5):
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"evidence {eid} has invalid quality_score: {e.get('quality_score')!r}")
        if e.get("hop") not in hop_numbers:
            errors.append(f"evidence {eid} references missing hop: {e.get('hop')} (orphan hop)")
        if e.get("claim_id") and e.get("claim_id") not in claim_ids:
            errors.append(f"evidence {eid} references missing claim_id: {e.get('claim_id')}")

        if contains_secret(json.dumps(e, ensure_ascii=False)):
            warnings.append(f"evidence {eid} may contain a secret/token; redact before sharing")

    # readiness gates (warnings — these are coverage signals, not validity)
    if len(hops) < hop_target:
        warnings.append(f"hop count {len(hops)} below effort target {hop_target} (fine only if gaps are explicit)")
    source_types = {e.get("source_type") for e in evidence if e.get("source_type")}
    if len(source_types) < class_target:
        warnings.append(f"source-class coverage {len(source_types)} below effort target {class_target}")
    has_contradiction = any(e.get("stance") == "contradicts" for e in evidence) or \
                        any(h.get("mode") == "contradict" for h in hops)
    if not has_contradiction:
        warnings.append("no red-team pass recorded — run a contradiction query before finalizing")
    open_claims = [c.get("id") for c in claims if not c.get("evidence_ids")]
    if open_claims:
        warnings.append(f"open claims (no evidence): {', '.join(open_claims)} — declare them, don't silently drop")

    result = {
        "run_dir": str(run_dir),
        "question": data.get("question"),
        "effort": data.get("effort"),
        "hop_count": len(hops),
        "hop_target": hop_target,
        "evidence_count": len(evidence),
        "claim_count": len(claims),
        "counter_evidence_count": len(data.get("counter_evidence", [])),
        "source_classes": sorted(source_types),
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if errors else 0


def cmd_export(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    data = read_ledger(run_dir)
    md = _render_ledger_md(data)
    out_path = run_dir / "ledger.md"
    out_path.write_text(md, encoding="utf-8")
    print(str(out_path))
    return 0


def _render_ledger_md(data: dict) -> str:
    lines: list[str] = []
    lines.append(f"# Research Ledger — {data.get('question', '')}")
    lines.append("")
    lines.append(f"- run_id: `{data.get('run_id')}`")
    lines.append(f"- effort: {data.get('effort')}")
    lines.append(f"- deliverable: {data.get('deliverable')}")
    lines.append(f"- created_at: {data.get('created_at')}")
    if data.get("aspects"):
        lines.append(f"- aspects: {', '.join(data['aspects'])}")
    lines.append("")

    lines.append("## Claims")
    lines.append("")
    if not data.get("claims"):
        lines.append("_(none)_")
    for c in data.get("claims", []):
        evs = ", ".join(c.get("evidence_ids") or []) or "—"
        base = c.get("confidence", "med")
        derived = c.get("confidence_derived", base)
        agree = c.get("agreement", "unresolved")
        conf = base if derived == base else f"{base}→{derived}"
        lines.append(f"- **{c.get('id')}** ({conf}, {agree}): "
                     f"{c.get('text')}  _evidence: {evs}_")
    lines.append("")

    lines.append("## Evidence")
    lines.append("")
    if not data.get("evidence"):
        lines.append("_(none)_")
    for e in data.get("evidence", []):
        lines.append(f"- **{e.get('id')}** [{e.get('stance')}, q{e.get('quality_score')}] "
                     f"{e.get('title')} — {e.get('url')} "
                     f"(`{e.get('quote_or_locator')}`) "
                     f"_claim {e.get('claim_id') or '—'} / hop {e.get('hop')}_")
    lines.append("")

    lines.append("## Hops")
    lines.append("")
    if not data.get("hops"):
        lines.append("_(none)_")
    for h in sorted(data.get("hops", []), key=lambda x: x.get("n", 0)):
        lines.append(f"- **{h.get('n')}** [{h.get('mode')}] {h.get('tool')}: {h.get('query')}")
        if h.get("result_summary"):
            lines.append(f"    - result: {h.get('result_summary')}")
        if h.get("next_questions"):
            lines.append(f"    - next: {h.get('next_questions')}")
    lines.append("")

    lines.append("## Counter-evidence")
    lines.append("")
    if not data.get("counter_evidence"):
        lines.append("_(none)_")
    for ce in data.get("counter_evidence", []):
        lines.append(f"- claim {ce.get('claim_id')}: {ce.get('text')} "
                     f"_(evidence {', '.join(ce.get('evidence_ids') or [])})_")
    lines.append("")
    return "\n".join(lines)


# --- local research memory (cross-run evidence dedup) -----------------------

def _memory_records(ledger: dict) -> list[dict]:
    run_id = ledger.get("run_id")
    out = []
    for e in ledger.get("evidence", []):
        out.append({
            "run_id": run_id,
            "claim_id": e.get("claim_id"),
            "title": e.get("title"),
            "year": e.get("year"),
            "doi": e.get("doi"),
            "arxiv_id": e.get("arxiv_id"),
            "url": e.get("url"),
        })
    return out


def cmd_memory_index(args: argparse.Namespace) -> int:
    """Build a cross-run evidence index (DOI/arXiv/URL → run/claim)."""
    base = Path(args.base).expanduser().resolve()
    out = Path(args.out).expanduser().resolve() if args.out else base / ".research-memory.json"
    records: list[dict] = []
    if base.exists():
        for lp in sorted(base.rglob("ledger.json")):
            try:
                data = json.loads(lp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            records.extend(_memory_records(data))
    index = {"built_at": now_utc(), "base": str(base), "entries": records}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"indexed": len(records), "out": str(out)}, ensure_ascii=False, indent=2))
    return 0


def cmd_memory_check(args: argparse.Namespace) -> int:
    """Look up one identifier in the memory index."""
    index_path = Path(args.index).expanduser().resolve()
    if not index_path.exists():
        raise SystemExit(f"no memory index at {index_path}; run memory-index first")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    targets = []
    if args.doi:
        targets.append(("doi", args.doi))
    if args.arxiv_id:
        targets.append(("arxiv_id", args.arxiv_id))
    if args.url:
        targets.append(("url", args.url))
    if not targets:
        raise SystemExit("provide --doi, --arxiv-id, or --url")
    matches = []
    for e in index.get("entries", []):
        if any(e.get(f) == v for f, v in targets):
            matches.append(e)
    print(json.dumps({"matches": matches}, ensure_ascii=False, indent=2))
    return 0


def cmd_memory_dedup(args: argparse.Namespace) -> int:
    """Flag evidence in this run that already exists in other runs."""
    run_dir = Path(args.run_dir).expanduser().resolve()
    data = read_ledger(run_dir)
    index_path = Path(args.index).expanduser().resolve() if args.index else run_dir.parent / ".research-memory.json"
    if not index_path.exists():
        raise SystemExit(f"no memory index at {index_path}; run memory-index --base {run_dir.parent}")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    entries = index.get("entries", [])
    my_run = data.get("run_id")
    hits = 0
    for e in data.get("evidence", []):
        seen = [m for m in entries
                if m.get("run_id") != my_run
                and ((m.get("doi") and m.get("doi") == e.get("doi"))
                     or (m.get("arxiv_id") and m.get("arxiv_id") == e.get("arxiv_id"))
                     or (m.get("url") and m.get("url") == e.get("url")))]
        if seen:
            m = seen[0]
            hits += 1
            print(f"evidence {e.get('id')}: you already have evidence for this — "
                  f"run {m.get('run_id','?')[:8]}…, claim {m.get('claim_id') or '—'} "
                  f"({m.get('title','')[:60]})")
    print(json.dumps({"duplicates": hits}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage a versioned deep-research evidence ledger (JSON, schema v1)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create a run directory + empty ledger.json")
    p.add_argument("--question", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--effort", choices=sorted(EFFORT_DEFAULTS), default="deep")
    p.add_argument("--deliverable", default="")
    p.add_argument("--aspects", default="", help="comma-separated aspect list from the Map step")
    p.add_argument("--force", action="store_true", help="reset an existing non-empty run directory")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("add-hop", help="record one retrieval/inspection hop")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--hop", required=True, type=int)
    p.add_argument("--mode", choices=HOP_MODES, required=True)
    p.add_argument("--tool-or-source", required=True)
    p.add_argument("--query-or-action", required=True)
    p.add_argument("--result-summary", default="")
    p.add_argument("--next-questions", default="")
    p.set_defaults(func=cmd_add_hop)

    p = sub.add_parser("add-claim", help="register a claim")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--confidence", choices=CONFIDENCES, required=True)
    p.add_argument("--id", help="optional explicit claim id (e.g. C1); auto-assigned if omitted")
    p.set_defaults(func=cmd_add_claim)

    p = sub.add_parser("add-evidence", help="attach evidence to a claim")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--hop", required=True, type=int)
    p.add_argument("--source-id", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--url", required=True)
    p.add_argument("--source-type", choices=SOURCE_TYPES, required=True)
    p.add_argument("--quality-score", required=True, type=int)
    p.add_argument("--stance", choices=STANCES, required=True)
    p.add_argument("--claim-id", default="", help="claim this evidence supports/contradicts (must exist)")
    p.add_argument("--quote-or-locator", default="")
    p.add_argument("--confidence", choices=CONFIDENCES, default="med")
    p.add_argument("--doi", default=None)
    p.add_argument("--arxiv-id", default=None)
    p.add_argument("--year", type=int, default=None)
    p.add_argument("--id", help="optional explicit evidence id (e.g. E1)")
    p.set_defaults(func=cmd_add_evidence)

    p = sub.add_parser("status", help="hop budget vs actual, coverage, open claims")
    p.add_argument("--run-dir", required=True)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("lint", help="validate the ledger; exit 1 on errors")
    p.add_argument("--run-dir", required=True)
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("export", help="emit a human-readable ledger.md")
    p.add_argument("--run-dir", required=True)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("memory-index", help="build a cross-run evidence index")
    p.add_argument("--base", required=True, help="directory of run dirs (scanned for ledger.json)")
    p.add_argument("--out", default="", help="index file (default <base>/.research-memory.json)")
    p.set_defaults(func=cmd_memory_index)

    p = sub.add_parser("memory-check", help="look up a DOI/arXiv/URL in the memory index")
    p.add_argument("--index", required=True)
    p.add_argument("--doi", default=None)
    p.add_argument("--arxiv-id", default=None)
    p.add_argument("--url", default=None)
    p.set_defaults(func=cmd_memory_check)

    p = sub.add_parser("memory-dedup", help="flag evidence in a run already seen in other runs")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--index", default="", help="memory index (default <run-dir>/../.research-memory.json)")
    p.set_defaults(func=cmd_memory_dedup)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
