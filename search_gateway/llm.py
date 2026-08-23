"""DeepSeek LLM client (OpenAI-compatible REST, via httpx).

Used by answer synthesis and query expansion. deepseek-v4-flash is a reasoning
model — responses carry both `reasoning_content` (discarded) and `content`
(the actual answer), and reasoning tokens count toward max_tokens, so the
token budget is set generously.
"""

from __future__ import annotations

import json
import logging

import httpx

from .config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    LLM_ENABLED,
    LLM_MODEL,
    LLM_TIMEOUT,
)
from .extract.vault import load_secrets

logger = logging.getLogger("search_gateway.llm")

_api_key: str | None = None


def get_api_key() -> str:
    global _api_key
    if _api_key is None:
        _api_key = DEEPSEEK_API_KEY or load_secrets(
            "deepseek", {"DEEPSEEK_API_KEY"}).get("DEEPSEEK_API_KEY", "")
    return _api_key


def available() -> bool:
    """LLM is usable only when enabled AND a key is present."""
    return bool(LLM_ENABLED and get_api_key())


async def complete(messages: list[dict], max_tokens: int = 2048,
                   temperature: float = 0.3, thinking: bool = True,
                   reasoning_effort: str = "high") -> str:
    """Chat completion. Returns the assistant `content` (not reasoning).

    DeepSeek v4 specifics (from api-docs.deepseek.com):
      - Thinking mode is ON by default (effort "high"). Toggle with
        `thinking: {"type": "enabled"/"disabled"}`.
      - `temperature`/`top_p`/penalties are IGNORED while thinking is on —
        only set `temperature` when thinking is disabled.
      - Reasoning tokens count toward `max_tokens`; budget generously when
        thinking is on, and trim when off.
    """
    key = get_api_key()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY not set")

    payload: dict = {
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
        "thinking": {"type": "enabled" if thinking else "disabled"},
    }
    if thinking:
        payload["reasoning_effort"] = reasoning_effort
    else:
        payload["temperature"] = temperature

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
            resp = await client.post(f"{DEEPSEEK_BASE_URL}/chat/completions",
                                     headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"deepseek request failed: {exc}") from exc

    if "error" in data:
        raise RuntimeError(f"deepseek API error: {data['error']}")

    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError):
        logger.error("unexpected deepseek response: %s", json.dumps(data)[:400])
        return ""
