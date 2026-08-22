"""research_ledger.py CLI tests — the deep-research evidence ledger (stdlib
only, 760 lines). Exercises init → hop → claim → evidence → status → lint →
export → memory-index → memory-check → memory-dedup end to end in tmp dirs."""

from __future__ import annotations

import json
import os
import subprocess
import sys

LEDGER = os.path.join(os.path.dirname(__file__), "..", "skills",
                      "deep-research", "scripts", "research_ledger.py")


def _run(*args, cwd=None):
    return subprocess.run([sys.executable, LEDGER, *args], capture_output=True,
                          text=True, cwd=cwd, check=False)


import glob  # noqa: E402 — after the subprocess helper


def _init_run(base, question="How does X work?"):
    """init --out-dir creates <base>/<YYYYMMDD-HHMMSS>-<slug>/ledger.json."""
    r = _run("init", "--out-dir", base, "--question", question, "--effort", "deep")
    assert r.returncode == 0, r.stderr
    created = glob.glob(os.path.join(base, "*-*"))
    assert created, f"init created no run dir in {base}"
    created.sort(key=os.path.getmtime)  # newest last (glob order is arbitrary)
    return created[-1]


def test_full_ledger_lifecycle(tmp_path):
    base = str(tmp_path)
    run = _init_run(base)
    with open(os.path.join(run, "ledger.json")) as fh:
        ledger = json.load(fh)
    assert ledger["question"] == "How does X work?"
    assert ledger["schema"] == 1

    # hops: seed + verify + contradict (red-team pass)
    for i, mode in ((1, "seed"), (2, "verify"), (3, "contradict")):
        r = _run("add-hop", "--run-dir", run, "--hop", str(i), "--mode", mode,
                 "--tool-or-source", "searxng", "--query-or-action", "test query",
                 "--result-summary", "5 results")
        assert r.returncode == 0, r.stderr

    # claim
    r = _run("add-claim", "--run-dir", run, "--id", "C1",
             "--text", "Claim one", "--confidence", "med")
    assert r.returncode == 0, r.stderr

    # evidence attached to claim (supports + contradicts)
    r = _run("add-evidence", "--run-dir", run, "--id", "E1", "--hop", "1",
             "--claim-id", "C1", "--source-id", "https://example.com/",
             "--title", "Example Source", "--url", "https://example.com/",
             "--source-type", "web", "--quality-score", "4", "--stance", "supports",
             "--quote-or-locator", "p.1")
    assert r.returncode == 0, r.stderr
    r = _run("add-evidence", "--run-dir", run, "--id", "E2", "--hop", "3",
             "--claim-id", "C1", "--source-id", "https://counter.example/",
             "--title", "Counter Source", "--url", "https://counter.example/",
             "--source-type", "paper", "--quality-score", "4",
             "--stance", "contradicts", "--quote-or-locator", "p.2")
    assert r.returncode == 0, r.stderr

    # status: claim + evidence present
    r = _run("status", "--run-dir", run)
    assert r.returncode == 0, r.stderr
    assert "C1" in r.stdout

    # lint: green after evidence attached
    r = _run("lint", "--run-dir", run)
    assert r.returncode == 0, r.stdout

    # export: writes human-readable ledger.md, echoes the path
    r = _run("export", "--run-dir", run)
    assert r.returncode == 0, r.stderr
    md_path = r.stdout.strip()
    assert md_path.endswith("ledger.md")
    with open(md_path) as fh:
        assert "Claim one" in fh.read()

    # memory index + check + dedup across a second run
    base = str(tmp_path)
    r = _run("memory-index", "--base", base)
    assert r.returncode == 0, r.stderr
    index = os.path.join(base, ".research-memory.json")
    assert os.path.exists(index)
    r = _run("memory-check", "--index", index, "--url", "https://example.com/")
    assert r.returncode == 0, r.stderr
    assert "example.com" in r.stdout

    run2 = _init_run(base, "Second run")
    _run("add-hop", "--run-dir", run2, "--hop", "1", "--mode", "extract",
         "--tool-or-source", "openalex", "--query-or-action", "q")
    _run("add-claim", "--run-dir", run2, "--id", "C1",
         "--text", "Claim one", "--confidence", "med")
    _run("add-evidence", "--run-dir", run2, "--id", "E1", "--hop", "1",
         "--claim-id", "C1", "--source-id", "https://example.com/",
         "--title", "Example Source", "--url", "https://example.com/",
         "--source-type", "web", "--quality-score", "4", "--stance", "supports",
         "--quote-or-locator", "p.1")
    r = _run("memory-dedup", "--run-dir", run2, "--index", index)
    assert r.returncode == 0, r.stderr
    assert '"duplicates": 1' in r.stdout or "duplicates" in r.stdout
    assert "E1" in (r.stderr + r.stdout)  # flags the already-seen evidence


def test_ledger_lint_catches_open_claims(tmp_path):
    run = _init_run(str(tmp_path))
    # claim WITHOUT evidence → lint must fail
    _run("add-claim", "--run-dir", run, "--id", "C1",
         "--text", "Unsupported claim", "--confidence", "high")
    r = _run("lint", "--run-dir", run)
    assert r.returncode != 0
    status = _run("status", "--run-dir", run)
    assert "open" in status.stdout.lower()


def test_missing_ledger_fails_cleanly(tmp_path):
    empty = str(tmp_path / "nothing")
    os.makedirs(empty, exist_ok=True)
    r = _run("status", "--run-dir", empty)
    assert r.returncode != 0
    assert "ledger.json" in r.stderr


def test_export_writes_file_and_valid_json(tmp_path):
    run = _init_run(str(tmp_path))
    _run("add-hop", "--run-dir", run, "--hop", "1", "--mode", "seed",
         "--tool-or-source", "arxiv", "--query-or-action", "q", "--result-summary", "2")
    _run("add-claim", "--run-dir", run, "--id", "C1", "--text", "T",
         "--confidence", "low")
    r = _run("export", "--run-dir", run)
    assert r.returncode == 0, r.stderr
    # export writes ledger.md and echoes its path
    md_path = r.stdout.strip()
    assert md_path.endswith("ledger.md")
    with open(md_path) as fh:
        assert "C1" in fh.read()
    # ledger remains valid JSON after every command
    with open(os.path.join(run, "ledger.json")) as fh:
        json.load(fh)
