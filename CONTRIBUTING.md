# Contributing

## Setup

```bash
git clone <this-repo> && cd kortex-search
pip install -e .                 # editable install
cd infra && docker compose up -d # redis (AOF) + searxng (JSON, :8888)
cd ..
kortex-search check             # confirm 22 sources + Redis before you start
```

## Running tests

```bash
pytest -m "not slow"             # fast suite — no model downloads required
pytest                           # full suite, including `slow`-marked tests
```

The `slow` marker (`pyproject.toml`'s `[tool.pytest.ini_options]`) gates
tests that need the cross-encoder/bi-encoder models actually downloaded and
loaded — skip it for a quick local loop, include it before opening a PR that
touches `rerank.py`, `embeddings.py`, or anything in the fusion/dedup/MMR
path. `tests/test_contract.py` and `tests/test_mcp_handshake.py` are the two
tests that hold the tool/source surface to its documented contract — a
change to `server.py`'s tool signatures, `sources/__init__.py`'s `ALL_SOURCES`
registry, or `models.py`'s `Result` shape should make one of them fail if the
docs weren't updated to match.

## Lint

Keep changes ruff F-rules-clean (unused imports, undefined names, and the
rest of the `F` rule family) before opening a PR — this repo does not carry
style-only lint debt, and a clean `F`-rule pass is the bar for merge, not an
aspiration.

## Adding a source

Follow `docs/architecture.md#source-adapter-contract`: subclass `Source`,
implement `search()` (and `available()` for the `doctor` probe), emit
`Result` objects with the relevant `docs/meta-schema.md` keys populated,
register the instance in `ALL_SOURCES` (`sources/__init__.py`), and bump the
expected source count in `tests/test_contract.py`. That test asserts the
live registry size, so an unregistered or miscounted source fails CI
immediately.

## Docs voice

Every doc in this repo speaks in one of two registers — read `docs/voice.md`
before writing or editing any Markdown here. Reference docs (`docs/api/`,
`docs/config-reference.md`, `docs/deployment.md`,
`docs/mcp-registration.md`, `docs/security.md`, `docs/meta-schema.md`) are
concise, traceable, and calibrated on certainty. `README.md` and
`docs/architecture.md` are thesis-led narrative — open with the claim, defend
it with named files/numbers, end on synthesis. Both registers ban filler:
no "This section covers…", no restating the question, no unearned hedging.

## SemVer / CHANGELOG

Adding a tool is a **minor** version bump. Removing or renaming a tool, or
changing a `Result`/return-field shape, is **major**, with a deprecation
cycle — `docs/architecture.md#versioning` has the full rule.
`kortex_search/__init__.py`'s `__version__` is the single source of truth
for the current version; update `CHANGELOG.md` alongside any version bump,
describing the change from the consumer's point of view (what a client
integration would notice), not as a diff summary.

## Submodules

`diagram-design` (used by the `report` skill) is a git submodule — clone
with `git clone --recurse-submodules`, or run `git submodule update --init`
after a plain clone, or that directory will sit empty
(`docs/adrs/0006-skills-in-repo-submodule.md`).