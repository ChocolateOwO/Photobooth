"""System use cases."""

from __future__ import annotations

from dataclasses import dataclass

from photobooth.core.errors import PhotoboothError
from photobooth.modules.system.domain import (
    AppMetaRepository,
    ComponentState,
    HealthReport,
    InstanceFacts,
    InstanceFactsSource,
    VersionInfo,
)


@dataclass(frozen=True)
class SystemIdentity:
    instance: str
    app_version: str
    api_version: int
    git_commit: str | None


class InstanceStampMismatchError(PhotoboothError):
    def __init__(self, expected: str, found: str) -> None:
        super().__init__(f"database belongs to instance '{found}', not '{expected}'")


class SystemService:
    def __init__(self, repository: AppMetaRepository, identity: SystemIdentity) -> None:
        self._repository = repository
        self._identity = identity

    def health(self) -> HealthReport:
        db_state = ComponentState.OK if self._repository.ping() else ComponentState.ERROR
        return HealthReport(instance=self._identity.instance, database=db_state)

    def version(self) -> VersionInfo:
        return VersionInfo(
            app_version=self._identity.app_version,
            api_version=self._identity.api_version,
            instance=self._identity.instance,
            schema_revision=self._repository.schema_revision(),
            git_commit=self._identity.git_commit,
        )

    def stamp_instance(self) -> str:
        """Stamp a fresh database with this instance; refuse a database from another instance."""
        stored = self._repository.set_if_absent(
            AppMetaRepository.INSTANCE_KEY, self._identity.instance
        )
        if stored != self._identity.instance:
            raise InstanceStampMismatchError(self._identity.instance, stored)
        return stored


@dataclass(frozen=True)
class SystemDetails:
    version: VersionInfo
    health: HealthReport
    facts: InstanceFacts


class SystemDetailsService:
    """The organizer's System page: versions, health and the running booth's own facts."""

    def __init__(self, system: SystemService, facts: InstanceFactsSource) -> None:
        self._system = system
        self._facts = facts

    def details(self) -> SystemDetails:
        return SystemDetails(
            version=self._system.version(),
            health=self._system.health(),
            facts=self._facts.facts(),
        )
