"""Instance configuration loaded from `<instance>\\config\\photobooth.env` (UTF-8)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from photobooth.core.errors import ConfigurationError

Instance = Literal["dummy", "main"]
Profile = Literal["dev", "e2e", "test", "prod"]

KIOSK_ALLOWED_HOSTS: tuple[str, ...] = ("localhost", "127.0.0.1")


class AppSettings(BaseSettings):
    """Validated instance settings. Relative paths resolve against `instance_root`.

    The explicit env file is AUTHORITATIVE: process environment variables are never read, so an
    inherited PHOTOBOOTH_* variable in a shell can not redirect identity, paths or ports.
    """

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
    ui_port: int | None = Field(default=None, ge=1, le=65535)
    delivery_host: str = "0.0.0.0"  # noqa: S104 - delivery listener is intentionally LAN-facing
    delivery_port: int = Field(ge=1, le=65535)
    # The address guests' phones use in the QR link. Unset: the booth's own LAN address.
    delivery_public_host: str | None = None
    # Optional LAN listener for a second booth screen (a TV's browser). It serves the booth
    # screens only (never Admin) and the photos come from this PC's camera. Unset: no listener.
    screen_host: str = "0.0.0.0"  # noqa: S104 - the TV screen listener is LAN-facing by intent
    screen_port: int | None = Field(default=None, ge=1, le=65535)

    frontend_dist: Path | None = None
    git_commit: str | None = None
    max_request_bytes: int = 15 * 1024 * 1024

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Only explicit constructor values and the explicit env file; never os.environ.
        return (init_settings, dotenv_settings)

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

    @property
    def allowed_origins(self) -> frozenset[str]:
        """Exact browser origins allowed to send cookie-authenticated mutations."""
        ports = [self.kiosk_port] + ([self.ui_port] if self.ui_port is not None else [])
        return frozenset(f"http://{host}:{port}" for host in KIOSK_ALLOWED_HOSTS for port in ports)

    @classmethod
    def from_env_file(cls, env_file: Path, git_commit: str | None = None) -> AppSettings:
        """Load settings from an explicit UTF-8 env file (Thai paths supported).

        `git_commit` is informational only and is the single value supplied by the caller.
        """
        if not env_file.is_file():
            raise ConfigurationError(f"env file not found: {env_file}")
        try:
            return cls(_env_file=env_file, git_commit=git_commit)
        except ValueError as exc:
            raise ConfigurationError(f"invalid settings in {env_file}: {exc}") from exc
