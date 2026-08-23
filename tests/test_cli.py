"""CLI exit-code / output tests (fast — no network, no model loads).

`doctor` is intentionally not exercised here: it probes all 22 sources over
the network. Its structure is asserted by `test_contract.py` via the shared
`health.report()`; run `search-gateway doctor` by hand for a live report.
"""

import json
import subprocess
import sys

from search_gateway import __version__


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "search_gateway.cli", *args],
        capture_output=True, text=True, timeout=60,
    )


def test_version_exit_0():
    r = _run("version")
    assert r.returncode == 0
    assert r.stdout.strip() == __version__


def test_help_lists_subcommands():
    r = _run("--help")
    assert r.returncode == 0
    for cmd in ("serve", "doctor", "check", "version", "warm"):
        assert cmd in r.stdout


def test_check_reports_22_sources_and_exit_code_matches_redis():
    r = _run("check")
    out = json.loads(r.stdout)
    assert out["sources"] == 22
    assert "redis" in out and "llm" in out
    # exit 0 iff Redis is reachable (the strict gate)
    assert (r.returncode == 0) == bool(out["redis"].get("ok"))
