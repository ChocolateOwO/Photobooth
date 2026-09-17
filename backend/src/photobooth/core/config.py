"""Instance configuration loaded from `<instance>\\config\\photobooth.env` (UTF-8)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from photobooth.core.errors import ConfigurationError

Instance = Literal["dummy", "main"]
Profile = Literal["dev", "e2e", "test", "prod"]

KIOSK_ALLOWED_HOSTS: tuple[str, ...] = ("localhost", "127.0.0.1")


class AppSettings(BaseSettings):
    """Validated instance settings. Relative paths resolve against `instance_root`."""

    model_config = SettingsConfigDict(
        env_prefix="PHOTOBOOTH_",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    instance: Instance
    profile: Profile = "dev"
    instance_root: Path

    data_dir: Path = Path("data")
    db_path: Path = Path("data/db/photobooth.sqlite")
    storage_dir: Path = Path("data/storage")
    backups_dir: Path = Path("data/backups")
    logs_dir: Path = Path("data/logs")
    config_dir: Path = Path("config")

    kiosk_host: str = "127.0.0.1"
    kiosk_port: int = Field(ge=1, le=65535)
    delivery_host: str = "0.0.0.0"  # noqa: S104 - delivery listener is intentionally LAN-facing
    delivery_port: int = Field(ge=1, le=65535)

    frontend_dist: Path | None = None
    git_commit: str | None = None
    max_request_bytes: int = 15 * 1024 * 1024

    @model_validator(mode="after")
    def _resolve_paths(self) -> AppSettings:
        root = self.instance_root
        if not root.is_absolute():
            raise ValueError("PHOTOBOOTH_INSTANCE_ROOT must be an absolute path")
        for name in ("data_dir", "db_path", "storage_dir", "backups_dir", "logs_dir", "config_dir"):
            value: Path = getattr(self, name)
            if not value.is_absolute():
                object.__setattr__(self, name, root / value)
        if self.frontend_dist is not None and not self.frontend_dist.is_absolute():
            object.__setattr__(self, "frontend_dist", root / self.frontend_dist)
        return self

    @property
    def runtime_dir(self) -> Path:
        """Holds process-local secrets such as the pairing code (never in git)."""
        return self.config_dir / "runtime"

    @property
    def lock_path(self) -> Path:
        """Canonical per-instance lock, independent of configurable data paths.

        Every server, migration and credential-writing command for this instance root takes the
        same lock, so overriding PHOTOBOOTH_DATA_DIR cannot create a second, parallel lock.
        """
        return self.instance_root / "data" / "instance.lock"

    @property
    def device_cookie_name(self) -> str:
        return f"pb_device_{self.instance}"

    @classmethod
    def from_env_file(cls, env_file: Path) -> AppSettings:
        """Load settings from an explicit UTF-8 env file (Thai paths supported)."""
        if not env_file.is_file():
            raise ConfigurationError(f"env file not found: {env_file}")
        try:
            return cls(_env_file=env_file)
        except ValueError as exc:
            raise ConfigurationError(f"invalid settings in {env_file}: {exc}") from exc
