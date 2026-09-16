from __future__ import annotations

import logging
import secrets
from pathlib import Path

from photobooth.core.logging import configure_logging, redact


def test_delivery_token_path_is_hashed() -> None:
    token = secrets.token_urlsafe(32)
    line = f"GET /d/{token}/all.zip 200"
    out = redact(line)
    assert token not in out
    assert out.startswith("GET /d/") and out.endswith("/all.zip 200")


def test_alive_path_is_kept() -> None:
    assert redact("GET /d/_alive") == "GET /d/_alive"


def test_pairing_code_query_is_redacted() -> None:
    code = secrets.token_urlsafe(32)
    out = redact(f"GET /kiosk/pair?code={code} 303")
    assert code not in out
    assert "code=[REDACTED]" in out


def test_device_cookie_is_redacted() -> None:
    value = secrets.token_urlsafe(32)
    out = redact(f"cookie: pb_device_dummy={value}; other=1")
    assert value not in out


def test_secret_assignments_are_redacted() -> None:
    out = redact("PHOTOBOOTH_ADMIN_PASSWORD=hunter2hunter2 DRIVE_REFRESH_TOKEN: abc123xyz")
    assert "hunter2hunter2" not in out
    assert "abc123xyz" not in out


def test_log_files_never_contain_secrets(thai_root: Path) -> None:
    token = secrets.token_urlsafe(32)
    code = secrets.token_urlsafe(32)
    configure_logging(thai_root / "logs")
    try:
        log = logging.getLogger("photobooth.test")
        log.info("request path=/d/%s", token)
        log.warning("pair attempt /kiosk/pair?code=%s", code)
        try:
            raise ValueError(f"boom /d/{token}")
        except ValueError:
            log.exception("failure")
        logging.getLogger("uvicorn.access").info("GET /d/%s 200", token)
    finally:
        for handler in logging.getLogger().handlers:
            handler.flush()
            handler.close()
        logging.getLogger().handlers.clear()

    content = (thai_root / "logs" / "photobooth.log").read_text(encoding="utf-8")
    assert "request path=/d/" in content
    assert token not in content
    assert code not in content
