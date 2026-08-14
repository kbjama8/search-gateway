# -*- coding: utf-8 -*-
"""Regression tests for the Phase 4 hardening features.

Pure + Redis-only checks (no network, no model loads) so they stay fast and
deterministic in CI.
"""

import json

from search_gateway import saved_queries, stats
from search_gateway.embeddings import cjk_dominant


def test_cjk_dominant_detection():
    assert cjk_dominant(["The quick brown fox", "A survey of RAG"]) is False
    assert cjk_dominant(["深度学习大模型综述", "这是中文内容测试"]) is True
    # below the 0.25 share threshold → stays English path
    assert cjk_dominant(["english words here", "another english doc",
                         "one 中文 doc among many english words"]) is False


def test_ledger_health_scans_ledgers(monkeypatch, tmp_path):
    run = tmp_path / "run1"
    run.mkdir()
    ledger = {
        "schema": 1, "run_id": "abc", "question": "q", "effort": "standard",
        "claims": [
            {"id": "C1", "evidence_ids": ["E1"]},
            {"id": "C2", "evidence_ids": []},
        ],
        "evidence": [{"id": "E1", "claim_id": "C1"}],
        "hops": [], "counter_evidence": [],
    }
    (run / "ledger.json").write_text(json.dumps(ledger))
    monkeypatch.setattr(stats, "LEDGER_DIR", str(tmp_path))
    health = stats.ledger_health()
    assert health["run_count"] == 1
    assert health["claim_count"] == 2
    assert health["open_claims"] == 1
    assert health["runs_with_open_claims"] == 1


def test_saved_queries_crud():
    name = "test-crud-query"
    saved_queries.delete(name)
    assert "saved" in saved_queries.save(name, "test query", sources=["searxng"])
    names = {q.get("name") for q in saved_queries.list_all()}
    assert name in names
    assert saved_queries.delete(name).get("deleted") is True
