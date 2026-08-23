"""Extraction tiering — route each source through its cheapest viable tier.

Tiers and costs (relative latency + ban-risk):
  api     (1)  public HTTP APIs — free, fast, no masks involved
  cli     (3)  CLI tools — subprocess cost, retry logic, occasional friction
  browser (10) cookie-logged / JS-gated surfaces — slowest, highest risk

The default fan-out already avoids browser sources (config.DEFAULT_SOURCES);
this module makes that a *consequence* of cost instead of a hardcoded list,
so new sources declare a tier preference and routing follows automatically.
"""

from __future__ import annotations

from ..config import FALLBACK_CHAINS
from ..sources.base import Source

TIER_COST = {"api": 1, "cli": 3, "browser": 10}

# Preferred tier order per source. Browser tier is last for everything; it is
# the most expensive unit of extraction this gateway can spend.
SOURCE_TIERS: dict[str, tuple[str, ...]] = {
    "searxng": ("api",), "exa": ("cli",), "github": ("api",),
    "youtube": ("cli",), "bilibili": ("api",), "v2ex": ("api",),
    "stackoverflow": ("api",), "arxiv": ("api",), "openalex": ("api",),
    "crossref": ("api",), "semantic_scholar": ("api",), "web": ("api",),
    "twitter": ("cli", "browser"), "reddit": ("browser",),
    "facebook": ("browser",), "instagram": ("browser",),
    "xiaohongshu": ("browser",), "linkedin": ("cli", "browser"),
    "zhihu": ("api", "browser"), "weibo": ("api", "browser"),
    "baidu": ("api",), "toutiao": ("api",),
}

DEFAULT_TIERS: tuple[str, ...] = ("api", "cli", "browser")


def tiers_for(name: str) -> tuple[str, ...]:
    """Preferred tier order for a source (falls back to api → cli → browser)."""
    return SOURCE_TIERS.get(name, DEFAULT_TIERS)


def cost_of(tier: str) -> int:
    return TIER_COST.get(tier, 10)


def tier_plan(source: Source) -> list[tuple[str, int, list[str]]]:
    """Return [(tier, cost, fallback_chain)] for a source, cheapest first.

    The fallback chain is the degrade order from `FALLBACK_CHAINS` filtered to
    the tiers this gateway can actually spend for the source — documentation
    and routing in one place.
    """
    plan = []
    for tier in tiers_for(source.name):
        chain = [step for step in FALLBACK_CHAINS.get(source.name, [])
                 if step != "skip"]
        plan.append((tier, cost_of(tier), chain))
    return plan


def cheapest_viable_tier(name: str, *, browser_allowed: bool = True) -> str:
    """The cheapest tier for a source; browser tier dropped unless allowed."""
    for tier in tiers_for(name):
        if tier == "browser" and not browser_allowed:
            continue
        return tier
    return "api"
