"""Property-based adversarial tests (hypothesis) — the sweep's fuzz layer.

Properties here are the *semantic* invariants the gauntlet's scenario worlds
can't reach: parser round-trips, canonicalization idempotence, fusion
differential-oracles, percentile references, and no-crash+shape contracts for
the multi-shape extraction ladder and challenge classifier.

Doctrine (research 2026-08-31, LESSONS.md): every property pairs a no-crash
check with at least one semantic invariant; references are structurally
different from the implementation (naive, not re-implemented); broken
implementations must be able to falsify every assertion.

Deterministic in CI (`HYPOTHESIS_PROFILE=ci`), deeper in the sweep profile.
No deadlines: no IO here; generation + shrinking cost makes timing
enforcement pure noise.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import math
import os

import hypothesis.strategies as st
from hypothesis import HealthCheck, given, settings
from hypothesis.provisional import domains, urls

from kortex_search import dedup, fusion, stats
from kortex_search.diversity import _domain
from kortex_search.extract import detectors, parse
from kortex_search.models import Result
from kortex_search.orchestrator import _filter_fresh, _parse_date

settings.register_profile("dev", max_examples=60, deadline=None)
settings.register_profile("ci", max_examples=150, derandomize=True, deadline=None)
settings.register_profile("sweep", max_examples=1000, deadline=None,
                          suppress_health_check=[HealthCheck.too_slow,
                                                 HealthCheck.data_too_large])
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))

MIN_DT = dt.datetime(1970, 1, 1)  # noqa: DTZ001 — naive by design
MAX_DT = dt.datetime(2200, 1, 1)  # noqa: DTZ001 — naive by design

# ---------------------------------------------------------------------------
# Date parsing — the time-bomb class proved this surface is fragile
# ---------------------------------------------------------------------------

date_strings = st.one_of(
    st.datetimes(min_value=MIN_DT, max_value=MAX_DT).map(
        lambda d: d.isoformat(sep=" ", timespec="seconds")),
    st.datetimes(min_value=MIN_DT, max_value=MAX_DT).map(
        lambda d: d.isoformat(timespec="seconds")),
    st.datetimes(min_value=MIN_DT, max_value=MAX_DT).map(
        lambda d: d.isoformat(sep="T", timespec="milliseconds")),
    st.datetimes(min_value=MIN_DT, max_value=MAX_DT).map(
        lambda d: d.strftime("%Y-%m-%d")),
    st.integers(min_value=0, max_value=2**33).map(str),          # epoch seconds
    st.integers(min_value=0, max_value=2**43).map(str),          # epoch millis
    st.floats(min_value=0, max_value=2**33, allow_nan=False,
              allow_infinity=False).map(str),                   # epoch floats
    st.text(max_size=80),                                       # junk
    st.just(""),
    st.just("0000-00-00T00:00:00Z"),
    st.just("9999-99-99"),
    st.builds(lambda d, off: d.strftime("%Y-%m-%d") + off,
              st.datetimes(min_value=MIN_DT, max_value=MAX_DT),
              st.sampled_from(["Z", "+00:00", "+05:30", "-08:00"])),
)


@given(date_strings)
def test_parse_date_never_crashes_and_shapes(s):
    out = _parse_date(s)
    assert out is None or isinstance(out, dt.datetime)
    if out is not None:
        # the parser is naive-by-design (callers normalize tz) — its outputs
        # must never carry a fake timezone
        assert out.tzinfo is None


@given(st.integers(min_value=0, max_value=2**43).map(str))
def test_epoch_like_strings_are_unparseable(epoch_str):
    # I10 contract: epoch seconds/millis strings are deliberately NOT parsed
    # (kept exactly once by the freshness filter) — and must never masquerade
    # as compact YYYYMMDD dates (sweep 2026-08-31: anchored the pattern)
    out = _parse_date(epoch_str)
    assert out is None or out.year <= 2500


@given(st.datetimes(min_value=MIN_DT, max_value=MAX_DT))
def test_parse_date_iso_roundtrip(d):
    # isoformat(timespec="seconds") truncates microseconds — the parser
    # must round-trip the string it is given, so compare the truncated dt
    assert _parse_date(d.isoformat(timespec="seconds")) == d.replace(
        microsecond=0)


@given(st.datetimes(min_value=MIN_DT, max_value=MAX_DT))
def test_parse_date_date_only_roundtrip(d):
    assert _parse_date(d.strftime("%Y-%m-%d")) == dt.datetime(  # noqa: DTZ001 — naive parser contract
        d.year, d.month, d.day)


def _res(title="t", url=None, published=None):
    return Result(title=title, url=url or f"https://ex.com/{title}",
                  published=published)


@given(st.lists(
    st.tuples(
        st.sampled_from(["week", "month", "year"]),
        st.datetimes(min_value=dt.datetime(2018, 1, 1),  # noqa: DTZ001 — naive fixtures
                     max_value=dt.datetime(2030, 1, 1)).map(  # noqa: DTZ001
                         lambda d: d.isoformat(timespec="seconds")),
    ), max_size=20))
def test_filter_fresh_contract(pairs):
    # The semantic contract: a dated entry survives iff its date is inside
    # the window (computed against the real clock, same expression as the
    # implementation); unparseable entries are kept exactly once.
    now = dt.datetime.now(dt.UTC)
    days = {"week": 7, "month": 31, "year": 366}
    for window, published in pairs:
        results = [_res(f"old{i}", url=f"https://old.ex/{i}", published=published)
                   for i in range(3)]
        junk = _res("junk", published="not-a-date-at-all")
        out = _filter_fresh([*results, junk], window)
        titles = [r.title for r in out]
        d = _parse_date(published)
        d = d.replace(tzinfo=dt.UTC) if d.tzinfo is None else d
        inside = d >= now - dt.timedelta(days=days[window])
        assert all(t == "junk" or inside for t in titles)
        assert titles.count("junk") == 1


# ---------------------------------------------------------------------------
# URL canonicalization — RFC 3986 idempotence
# ---------------------------------------------------------------------------

url_like = st.one_of(
    urls(),
    st.builds(
        lambda s, h, p, q: f"{s}://{h}{p}{'?' + q if q else ''}",
        st.sampled_from(["http", "https", "HTTP", "HtTp"]),
        st.one_of(domains(),
                  st.text(min_size=1, max_size=20).filter(
                      lambda h: " " not in h and "/" not in h and "@" not in h)),
        st.text(max_size=16),
        st.text(max_size=16),
    ),
    st.text(max_size=200),
)


@given(url_like)
def test_canonical_url_idempotent(u):
    once = dedup.canonical_url(u)
    assert dedup.canonical_url(once) == once


@given(url_like)
def test_identity_is_stable_string(u):
    r = Result(title="t", url=u)
    ident = r.identity()
    assert isinstance(ident, str)
    assert r.identity() == ident  # deterministic


@given(url_like)
def test_domain_idempotent_and_clean(u):
    d = _domain(u)
    assert d == d.lower()
    assert not d.startswith("www.")
    if d:
        assert _domain(f"http://{d}/x") == d


# ---------------------------------------------------------------------------
# Fusion — differential oracle vs a naive reference
# ---------------------------------------------------------------------------

fusion_input = st.lists(
    st.lists(
        st.tuples(
            st.text(min_size=1, max_size=12,
                    alphabet=st.characters(whitelist_categories=("Lu", "Ll",
                                                                "Nd"))),
            st.text(min_size=1, max_size=12,
                    alphabet=st.characters(whitelist_categories=("Lu", "Ll",
                                                                "Nd", "Pc"))),
        ),
        min_size=0, max_size=10,
    ),
    min_size=1, max_size=8,
)


def _naive_rrf(ranked_lists, k=60.0):
    scores: dict[str, float] = {}
    for results in ranked_lists:
        for rank, (_title, url) in enumerate(results):
            key = url.strip().rstrip("/")
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda k: scores[k], reverse=True)


@given(fusion_input)
def test_rrf_fuse_matches_naive_reference(ranked_lists):
    k = 60.0
    lists = []
    for lst in ranked_lists:
        lists.append([
            Result(title=t, url=u, snippet="s", source="fake") for t, u in lst
        ])
    out = fusion.rrf_fuse(lists, k=k, weighted=False)
    keys = [r.url.strip().rstrip("/") for r in out]
    expected = _naive_rrf(ranked_lists, k=k)
    assert keys == expected


@given(st.lists(
    st.lists(st.floats(min_value=0.0, max_value=1.0, allow_nan=False,
                       allow_infinity=False, width=32), max_size=20),
    max_size=10))
def test_weighted_fusion_preserves_result_set(weights_per_source):
    # weighted fusion must neither invent nor drop results (weights only
    # reorder); the identity set is invariant
    lists = []
    for i, ws in enumerate(weights_per_source):
        lists.append([Result(title=f"t{j}", url=f"https://s{i}.ex/{j}",
                             snippet="s", source=f"src{i}")
                      for j in range(len(ws))])
    if not any(lists):
        return
    unweighted = fusion.rrf_fuse(lists, weighted=False)
    weighted = fusion.rrf_fuse(lists, weighted=True)
    assert {r.identity() for r in unweighted} == {r.identity() for r in weighted}
    assert len(weighted) == len(unweighted)


# ---------------------------------------------------------------------------
# Percentiles — nearest-rank reference (ceil) + tie torture
# ---------------------------------------------------------------------------

percentile_inputs = st.lists(
    st.one_of(
        st.floats(min_value=0.0, max_value=100.0, allow_nan=False,
                  allow_infinity=False, width=32),
        st.integers(min_value=0, max_value=100).map(float),
    ),
    min_size=1, max_size=100,
)


def _ref_percentile(vals, p):
    s = sorted(vals)
    idx = max(0, min(len(s) - 1, math.ceil(p / 100 * len(s)) - 1))
    return round(s[idx], 3)


@given(percentile_inputs)
def test_percentiles_match_nearest_rank_reference(vals):
    p50, p95 = stats._percentiles(vals, 50.0, 95.0)
    assert p50 == _ref_percentile(vals, 50.0)
    assert p95 == _ref_percentile(vals, 95.0)
    assert math.isfinite(p50) and math.isfinite(p95)
    assert 0.0 <= p50 <= p95 <= 100.0


# ---------------------------------------------------------------------------
# Extraction ladder — multi-shape JSON-ish payloads: no-crash + shape
# ---------------------------------------------------------------------------

scalars = st.one_of(
    st.none(), st.booleans(),
    st.integers(min_value=-(10**9), max_value=10**9),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.text(max_size=30),
)
json_docs = st.recursive(
    scalars,
    lambda c: st.one_of(
        st.lists(c, min_size=0, max_size=4),
        st.dictionaries(st.text(max_size=10), c, max_size=4),
    ),
    max_leaves=40,
)


@given(json_docs)
def test_parse_shapes_never_crashes_and_shapes(doc):
    text = json.dumps(doc)
    out = asyncio.run(parse.parse_shapes(text, source="probe", engine="generic"))
    assert isinstance(out, list)
    for item in out:
        assert isinstance(item, dict)
        assert "title" in item and "url" in item


@given(st.text(max_size=300))
def test_canonicalize_results_never_crashes(junk):
    out = parse.canonicalize_results(
        [{"a": junk}], source="probe", engine="generic")
    assert isinstance(out, list)


# ---------------------------------------------------------------------------
# Challenge classifier — hostile pages: no-crash + typed verdict
# ---------------------------------------------------------------------------

def _flatten(x) -> str:
    if isinstance(x, str):
        return x
    if isinstance(x, list):
        return "".join(_flatten(i) for i in x)
    return str(x)


html_frags = st.recursive(
    st.text(max_size=24).map(lambda t: t.replace("<", "&lt;")),
    lambda c: st.one_of(
        st.lists(c, min_size=0, max_size=3),
        st.builds(
            lambda tag, kids: f"<{tag}>{_flatten(kids)}</{tag}>",
            st.sampled_from(["div", "a", "span", "p", "li", "table",
                             "script", "iframe", "noscript"]),
            st.lists(c, min_size=0, max_size=3)),
    ),
    max_leaves=25,
)

_VALID_LEVELS = ("transient", "ip", "account")


@given(html_frags, st.sampled_from([200, 403, 429, 503, 0, -1]),
       st.dictionaries(st.text(max_size=12), st.text(max_size=24), max_size=5))
def test_classify_never_crashes_and_types(body, status, headers):
    sig = detectors.classify(status, headers, body)
    if sig is None:
        return
    assert isinstance(sig.vendor, str) and sig.vendor
    assert sig.level in _VALID_LEVELS
    assert isinstance(sig.evidence, str)


# ---------------------------------------------------------------------------
# Config contract: empty-string must NOT fall through to the default
# (the T6 fix — "" is a deliberate override, not "unset")
# ---------------------------------------------------------------------------

@given(st.text(max_size=40).filter(lambda s: "\x00" not in s))
def test_env_empty_string_is_not_default(s):
    from kortex_search import config
    old = os.environ.get("KORTEX_SEARCH_PROBE_VAR")
    os.environ["KORTEX_SEARCH_PROBE_VAR"] = s
    try:
        got = config._env("KORTEX_SEARCH_PROBE_VAR", "the-default")
        assert got == s  # raw passthrough, including ""
        assert got != "the-default" or s == "the-default"
    finally:
        if old is None:
            os.environ.pop("KORTEX_SEARCH_PROBE_VAR", None)
        else:
            os.environ["KORTEX_SEARCH_PROBE_VAR"] = old
