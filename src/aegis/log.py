"""Structured JSON-lines logging with rotation (P0.1).

Every module logs through the standard library logging module; this module
configures the root handlers once at startup:

- Console: human-readable, for development.
- File: one JSON object per line, rotated, for machine analysis later -
  the trade log and the system log must both be queryable, not grep-able.

Extra fields passed via ``logger.info("msg", extra={...})`` are merged into
the JSON object, so events can carry structured context (symbol, order id,
slippage, regime label) without format strings.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import UTC, datetime
from pathlib import Path

# Attributes belonging to LogRecord itself; anything else came in via `extra`.
_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonLinesFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(
    log_dir: str | Path = "logs",
    level: str = "INFO",
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Configure root logging. Idempotent - safe to call once at every entrypoint."""
    root = logging.getLogger()
    root.setLevel(level.upper())

    # Remove handlers from any previous call (idempotency for tests/restarts).
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
    root.addHandler(console)

    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        directory / "aegis.jsonl",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(JsonLinesFormatter())
    root.addHandler(file_handler)
