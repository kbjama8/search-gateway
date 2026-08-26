"""Model-path tests — @pytest.mark.slow, skipped when the HF cache is cold.

CI runs `-m "not slow"`; these are for a machine with the models downloaded.
"""

import pytest

from kortex_search.models import Result


@pytest.mark.slow
def test_embed_path_if_cached():
    from kortex_search import embeddings

    model = embeddings._get_model()
    if model is None:
        pytest.skip("embed model not cached / unavailable")
    vecs = embeddings.encode(["hello world", "a second document"])
    assert vecs is not None and vecs.shape[0] == 2


@pytest.mark.slow
def test_rerank_path_if_cached():
    from kortex_search import rerank

    model = rerank._get_model()
    if model is None:
        pytest.skip("rerank model not cached / unavailable")
    rs = [Result(title=f"t{i}", url=f"u{i}", snippet=f"s{i}") for i in range(3)]
    out = rerank.rerank("query", rs)
    assert len(out) == 3


@pytest.mark.slow
def test_onnx_rerank_backend():
    """The ONNX backend loads (or falls back to torch) and re-ranks. Runs in a
    fresh interpreter so the module-level singleton is not polluted."""
    import subprocess
    import sys

    script = (
        "import os\n"
        "os.environ['KORTEX_SEARCH_INFERENCE_BACKEND'] = 'onnx_int8'\n"
        "os.environ['SEMANTIC_RERANK'] = '1'\n"  # test_smoke leaks SEMANTIC_RERANK=0
        "from kortex_search import rerank\n"
        "from kortex_search.models import Result\n"
        "rs = [Result(title=f't{i}', url=f'u{i}', snippet=f's{i}') for i in range(5)]\n"
        "assert len(rerank.rerank('query', rs)) == 5\n"
        "assert rerank.status()['loaded'] is True\n"
        "print('onnx backend:', rerank.status()['backend'], '->', rerank.status()['model'])\n"
    )
    r = subprocess.run([sys.executable, "-c", script],
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr
    assert "onnx backend:" in r.stdout
