"""Error types shared across the backend."""


class PhotoboothError(Exception):
    """Base class for all expected backend errors."""


class ConfigurationError(PhotoboothError):
    """Settings are missing or invalid."""


class InstanceGuardError(PhotoboothError):
    """A startup safety check failed; the instance must not start."""

    def __init__(self, check: str, message: str) -> None:
        super().__init__(f"[{check}] {message}")
        self.check = check


class InstanceLockedError(InstanceGuardError):
    """Another backend process already owns this instance."""

    def __init__(self, lock_path: str) -> None:
        super().__init__("instance_lock", f"instance already running (lock held: {lock_path})")


class BackupError(PhotoboothError):
    """A database backup could not be created or failed verification."""
