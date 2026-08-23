"""Extraction layer — the v0.4 overhaul (Project Gatekeeper).

Sub-modules:
  parse.py        multi-shape parsing (JSON → JSON-LD → CSS → regex → LLM)
  detectors.py    block & challenge intelligence (vendor signatures → action ladder)
  router.py       extraction tiering (api=1, cli=3, browser=10)
  scheduler.py    browser budget + jittered pacing
  profiles.py     browser profile farm + health state machine
  fingerprints.py fingerprint bundles + coherence lint + geo alignment
  proxies.py      env-gated proxy gateway (sticky sessions, geo grammar)
  http.py         HTTP facade with optional TLS/JA3 impersonation
  camoufox.py     Camoufox anonymous-tier adapter (experimental, lazy)

Everything here fails toward its input: a disabled capability is a no-op, an
unavailable dependency degrades the stage rather than raising.
"""

from .detectors import BlockSignal, classify
from .parse import canonicalize_results, parse_jsonld, parse_shapes

__all__ = [
    "BlockSignal",
    "canonicalize_results",
    "classify",
    "parse_jsonld",
    "parse_shapes",
]
