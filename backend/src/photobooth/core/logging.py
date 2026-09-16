"""Logging setup with mandatory redaction of tokens, pairing codes, cookies and passwords."""

from __future__ import annotations

import hashlib
import logging
import logging.handlers
import re
from pathlib import Path

_DELIVERY_PATH = re.compile(r"/d/(?!_alive\b)([A-Za-z0-9_\-]{8,})")
_SECRET_QUERY = re.compile(r"(?i)\b(code|token|password|secret)=([^&\s\"']+)")
_COOKIE = re.compile(r"(?i)\b(pb_device_[a-z]+)=([^;\s\"']+)")
_ASSIGNMENT = re.compile(r"(?i)\b([A-Z0-9_]*(PASSWORD|SECRET|TOKEN))\s*[:=]\s*([^\s,;\"']+)")

REDACTED = "[REDACTED]"


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def redact(text: str) -> str:
    """Remove secret material from a log line. Delivery tokens become a short hash."""
    text = _DELIVERY_PATH.sub(lambda m: f"/d/{_short_hash(m.group(1))}", text)
    text = _SECRET_QUERY.sub(lambda m: f"{m.group(1)}={REDACTED}", text)
    text = _COOKIE.sub(lambda m: f"{m.group(1)}={REDACTED}", text)
    return _ASSIGNMENT.sub(lambda m: f"{m.group(1)}={REDACTED}", text)


class RedactingFilter(logging.Filter):
    """Rewrites every record's final message so no handler can emit a secret."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = redact(message)
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def configure_logging(logs_dir: Path | None, level: int = logging.INFO) -> None:
    """Configure root + uvicorn loggers. Uvicorn access logging is disabled entirely."""
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    redactor = RedactingFilter()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(redactor)
    root.addHandler(console)

    if logs_dir is not None:
        logs_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            logs_dir / "photobooth.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redactor)
        root.addHandler(file_handler)

    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    access.disabled = True
