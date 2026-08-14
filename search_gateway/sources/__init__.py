# -*- coding: utf-8 -*-
"""Source registry."""

from .base import Source
from .searxng import SearXNGSource
from .exa import ExaSource
from .twitter import TwitterSource
from .reddit import RedditSource
from .github import GitHubSource
from .youtube import YouTubeSource
from .facebook import FacebookSource
from .instagram import InstagramSource
from .bilibili import BilibiliSource
from .linkedin import LinkedInSource
from .v2ex import V2EXSource
from .xiaohongshu import XiaohongshuSource
from .web import WebSource
from .arxiv import ArxivSource
from .openalex import OpenAlexSource
from .crossref import CrossrefSource
from .stackoverflow import StackOverflowSource
from .semantic_scholar import SemanticScholarSource

ALL_SOURCES: dict[str, Source] = {
    s.name: s
    for s in (
        SearXNGSource(),
        ExaSource(),
        TwitterSource(),
        RedditSource(),
        GitHubSource(),
        YouTubeSource(),
        FacebookSource(),
        InstagramSource(),
        BilibiliSource(),
        LinkedInSource(),
        V2EXSource(),
        XiaohongshuSource(),
        WebSource(),
        ArxivSource(),
        OpenAlexSource(),
        CrossrefSource(),
        StackOverflowSource(),
        SemanticScholarSource(),
    )
}


def get_sources(names: list[str]) -> list[Source]:
    return [ALL_SOURCES[n] for n in names if n in ALL_SOURCES]


def valid_names() -> list[str]:
    return sorted(ALL_SOURCES.keys())
