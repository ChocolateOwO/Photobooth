"""System domain: value objects and repository interface (no framework imports)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum


class ComponentState(StrEnum):
    OK = "ok"
    ERROR = "error"


@dataclass(frozen=True)
class HealthReport:
    instance: str
    database: ComponentState

    @property
    def status(self) -> ComponentState:
        return ComponentState.OK if self.database is ComponentState.OK else ComponentState.ERROR


@dataclass(frozen=True)
class VersionInfo:
    app_version: str
    api_version: int
    instance: str
    schema_revision: str | None
    git_commit: str | None


class AppMetaRepository(ABC):
    """Persistence port for the `app_meta` key/value table."""

    INSTANCE_KEY = "instance"

    @abstractmethod
    def get(self, key: str) -> str | None: ...

    @abstractmethod
    def set_if_absent(self, key: str, value: str) -> str:
        """Store `value` unless the key exists; return the stored value either way."""

    @abstractmethod
    def ping(self) -> bool:
        """True when the database answers a trivial query."""

    @abstractmethod
    def schema_revision(self) -> str | None: ...

    def read_instance(self) -> str | None:
        return self.get(self.INSTANCE_KEY)
