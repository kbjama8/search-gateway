"""Structured logging setup.

Logs always go to **stderr**, never stdout — stdout is the MCP stdio protocol
wire. `KORTEX_SEARCH_LOG_FMT=json` emits one JSON object per line (for
systemd/journald); `text` is the human-readable default.
"""

from __future__ import annotations

import json
import logging
import sys

from .config import LOG_FMT, LOG_LEVEL


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    """Route all logging to stderr with the configured format + level."""
    if LOG_FMT == "json":
        fmt = JsonFormatter()
    else:
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(LOG_LEVEL.upper())
