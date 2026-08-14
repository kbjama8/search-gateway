# -*- coding: utf-8 -*-
"""Model-path tests — @pytest.mark.slow, skipped when the HF cache is cold.

CI runs `-m "not slow"`; these are for a machine with the models downloaded.
"""

import pytest

from search_gateway.models import Result


@pytest.mark.slow
def test_embed_path_if_cached():
    from search_gateway import embeddings

    model = embeddings._get_model()
    if model is None:
        pytest.skip("embed model not cached / unavailable")
    vecs = embeddings.encode(["hello world", "a second document"])
    assert vecs is not None and vecs.shape[0] == 2


@pytest.mark.slow
def test_rerank_path_if_cached():
    from search_gateway import rerank

    model = rerank._get_model()
    if model is None:
        pytest.skip("rerank model not cached / unavailable")
    rs = [Result(title=f"t{i}", url=f"u{i}", snippet=f"s{i}") for i in range(3)]
    out = rerank.rerank("query", rs)
    assert len(out) == 3
