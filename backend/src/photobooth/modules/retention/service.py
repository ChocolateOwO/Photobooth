"""Retention use cases: keep the policies, count what a cleanup would delete, and delete it."""

from __future__ import annotations

import contextlib
import logging
import threading
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from photobooth.modules.retention.domain import (
    Category,
    Housekeeping,
    PolicyChangedError,
    PolicyInUseError,
    PolicyNotFoundError,
    RetentionError,
    RetentionPolicy,
    RetentionReport,
    RetentionRepository,
    RetentionRun,
    Tally,
    Trigger,
    cutoff,
)

logger = logging.getLogger(__name__)

# The schedule: a cleanup at most this often while the booth runs (and once at start).
SCHEDULE_EVERY = timedelta(hours=1)

Counted = tuple[int, int, int]  # (items done, their bytes, items that could not be done)


class VisitData(Protocol):
    """Guests' visits and their files (the sessions module). Each visit is judged by the policy
    values it froze when it started, against `now`. Only visits that are over are ever touched;
    each one is handled while it is locked, files before the rows that name them."""

    def purge_originals(self, now: datetime, dry_run: bool) -> Counted: ...

    def purge_outputs(self, now: datetime, dry_run: bool) -> Counted:
        """Finished photos; their take-home links are revoked with them."""
        ...

    def anonymize_visits(self, now: datetime, dry_run: bool) -> Counted: ...

    def delete_visits(self, now: datetime, dry_run: bool) -> Counted: ...

    def delete_event_visits(self, profile_id: str, dry_run: bool) -> Counted:
        """Every visit of one event, for its permanent deletion. Raises RetentionError while
        one of them is still going."""
        ...


class ActivityData(Protocol):
    def purge(self, before: datetime, dry_run: bool) -> int: ...


class InstanceFiles(Protocol):
    """Files of this instance only (temporary files, database backups, application logs)."""

    def temp(self, before: datetime, dry_run: bool) -> Counted: ...

    def backups(self, before: datetime, dry_run: bool) -> Counted:
        """Backups older than `before`; the newest backup is always kept."""
        ...

    def app_logs(self, before: datetime, dry_run: bool) -> Counted:
        """Rotated application logs older than `before`; never the log being written."""
        ...


class EventRemoval(Protocol):
    """Permanent deletion of an event profile that was deleted (the event_profiles module)."""

    def deleted(self, profile_id: str) -> bool:
        """True for a profile that exists and is deleted (soft); False for a live one. Raises
        RetentionError for an unknown profile."""
        ...

    def remove(self, profile_id: str) -> None: ...

    def locked(self, profile_id: str) -> AbstractContextManager[None]:
        """Holds the event still: no restore, activation or change while it is held."""
        ...


class PolicyUsage(Protocol):
    """How many Event Profiles select a policy, deleted ones included (the event_profiles
    module): a policy in use can not be deleted."""

    def profiles_using(self, policy_id: str) -> int: ...

    def held(self) -> AbstractContextManager[None]:
        """Holds every profile still: none is created or changed while it is held."""
        ...


class _NoUsage:
    def profiles_using(self, policy_id: str) -> int:
        return 0

    def held(self) -> AbstractContextManager[None]:
        return contextlib.nullcontext()


class RetentionService:
    def __init__(
        self,
        repository: RetentionRepository,
        visits: VisitData,
        activity: ActivityData,
        files: InstanceFiles,
        events: EventRemoval,
        clock: Callable[[], datetime] | None = None,
        usage: PolicyUsage | None = None,
        new_id: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._repository = repository
        self._visits = visits
        self._activity = activity
        self._files = files
        self._events = events
        self._clock = clock or (lambda: datetime.now(UTC))
        self._usage = usage or _NoUsage()
        self._new_id = new_id
        # One cleanup at a time: a manual run and the schedule never overlap.
        self._running = threading.Lock()
        # Policy changes one at a time, so "in use" and "default" checks hold until they land.
        self._editing = threading.Lock()

    # ---- the policies ----------------------------------------------------------------------------

    def policies(self) -> list[RetentionPolicy]:
        return self._repository.policies()

    def policy(self, policy_id: str) -> RetentionPolicy:
        found = self._repository.policy(policy_id)
        if found is None:
            raise PolicyNotFoundError()
        return found

    def default_policy(self) -> RetentionPolicy:
        for policy in self._repository.policies():
            if policy.is_default:
                return policy
        return RetentionPolicy(is_default=True)  # never reached: migration 0012 seeds one

    def usage(self, policy_id: str) -> int:
        return self._usage.profiles_using(policy_id)

    def create_policy(self, policy: RetentionPolicy) -> RetentionPolicy:
        fresh = replace(
            policy,
            id=self._new_id(),
            name=" ".join(policy.name.split()),
            is_default=False,
            revision=1,
        )
        self._check(fresh)
        with self._editing:
            return self._repository.add_policy(fresh, self._clock())

    def update_policy(
        self, policy_id: str, policy: RetentionPolicy, expected_revision: int
    ) -> RetentionPolicy:
        """Changes the policy for visits that start from now on. Visits that already started
        keep the values they froze (their deadlines never move)."""
        with self._editing:
            current = self.policy(policy_id)
            changed = replace(
                policy,
                id=policy_id,
                name=" ".join(policy.name.split()),
                is_default=current.is_default,
            )
            self._check(changed)
            return self._repository.save_policy(changed, expected_revision, self._clock())

    def delete_policy(self, policy_id: str) -> None:
        # No profile can select the policy between the check and the deletion.
        with self._editing, self._usage.held():
            policy = self.policy(policy_id)
            if policy.is_default:
                raise PolicyInUseError("the default policy can not be deleted")
            used = self._usage.profiles_using(policy_id)
            if used:
                raise PolicyInUseError(
                    f"{used} event profile{'s' if used != 1 else ''} use{'' if used != 1 else 's'} "
                    "this policy (deleted profiles too); choose another policy for "
                    f"{'them' if used != 1 else 'it'} first"
                )
            if not self._repository.delete_policy(policy_id):
                raise PolicyNotFoundError()

    def make_default(self, policy_id: str) -> RetentionPolicy:
        """New Event Profiles start with this policy (existing ones keep theirs)."""
        with self._editing:
            made = self._repository.make_default(policy_id, self._clock())
            if made is None:
                raise PolicyNotFoundError()
            return made

    @staticmethod
    def _check(policy: RetentionPolicy) -> None:
        problems = policy.problems()
        if problems:
            raise RetentionError("; ".join(problems))

    # ---- housekeeping ---------------------------------------------------------------------------

    def housekeeping(self) -> Housekeeping:
        return self._repository.housekeeping()

    def update_housekeeping(
        self, housekeeping: Housekeeping, expected_revision: int
    ) -> Housekeeping:
        problems = housekeeping.problems()
        if problems:
            raise RetentionError("; ".join(problems))
        return self._repository.save_housekeeping(housekeeping, expected_revision, self._clock())

    # ---- cleaning up ---------------------------------------------------------------------------

    def run(
        self, trigger: Trigger, dry_run: bool, expected_revision: int | None = None
    ) -> RetentionReport:
        """Count (dry run) or delete everything past its time.

        Guests' data is judged visit by visit, by the policy values each visit froze when it
        started; the booth's own files by the housekeeping settings. `expected_revision` is the
        housekeeping revision the organizer saw in the dry run: a confirmed cleanup under
        settings changed since is refused (P11-008). Every category is tried even when another
        fails; what was deleted before a failure is still counted, and what could not be deleted
        is reported per category (never with a path) and tried again next time (P11-010).
        """
        with self._running:
            started = self._clock()
            rules = self.housekeeping()
            if expected_revision is not None and expected_revision != rules.revision:
                raise PolicyChangedError()
            steps: list[tuple[Category, Callable[[], Counted]]] = [
                (Category.ORIGINALS, lambda: self._visits.purge_originals(started, dry_run)),
                (Category.OUTPUTS, lambda: self._visits.purge_outputs(started, dry_run)),
                (
                    Category.VISITS_ANONYMIZED,
                    lambda: self._visits.anonymize_visits(started, dry_run),
                ),
                (Category.VISITS_DELETED, lambda: self._visits.delete_visits(started, dry_run)),
                (
                    Category.ACTIVITY,
                    lambda: (
                        self._activity.purge(cutoff(started, rules.activity_log_days), dry_run),
                        0,
                        0,
                    ),
                ),
                (
                    Category.TEMP,
                    lambda: self._files.temp(cutoff(started, hours=rules.temp_hours), dry_run),
                ),
                (
                    Category.BACKUPS,
                    lambda: self._files.backups(cutoff(started, rules.backup_days), dry_run),
                ),
                (
                    Category.APP_LOGS,
                    lambda: self._files.app_logs(cutoff(started, rules.app_log_days), dry_run),
                ),
            ]
            counts: dict[Category, Tally] = {}
            errors: list[str] = []
            broken: list[Category] = []
            for category, step in steps:
                try:
                    items, size, failed = step()
                except Exception as exc:
                    broken.append(category)
                    errors.append(f"{category.value}: {type(exc).__name__}")
                    logger.warning("retention %s failed (%s)", category.value, type(exc).__name__)
                    continue
                counts[category] = Tally(items=items, bytes=size, failed=failed)
                if failed:
                    errors.append(f"{category.value}: {failed} could not be deleted")
            report = RetentionReport(
                dry_run=dry_run,
                trigger=trigger,
                started_at=started,
                finished_at=self._clock(),
                housekeeping_revision=rules.revision,
                counts=counts,
                errors=tuple(errors),
                broken=tuple(broken),
            )
            self._remember(report)
            return report

    def scheduled(self) -> RetentionReport | None:
        """The periodic cleanup: at most once per SCHEDULE_EVERY while the booth runs."""
        last = self._repository.last_automatic_run()
        if last is not None and self._clock() - last < SCHEDULE_EVERY:
            return None
        return self.run(Trigger.SCHEDULE, dry_run=False)

    def runs(self, limit: int = 20) -> list[RetentionRun]:
        return self._repository.runs(max(1, min(limit, 100)))

    def last_cleanup(self) -> RetentionRun | None:
        """The latest cleanup that deleted, however many dry runs followed it (P12-R6)."""
        return self._repository.last_cleanup()

    # ---- deleting an event for good ------------------------------------------------------------

    def remove_event(self, profile_id: str, dry_run: bool) -> Counted:
        """A deleted event profile and all its visits, permanently. Refused for a live profile
        or while one of its visits is still going."""
        # Held for the whole removal: the event can not be restored, activated or changed
        # between the check and the last deletion (P11-003).
        with self._events.locked(profile_id), self._running:
            if not self._events.deleted(profile_id):
                raise RetentionError("only a deleted event can be deleted for good")
            counted = self._visits.delete_event_visits(profile_id, dry_run)
            if not dry_run:
                self._events.remove(profile_id)
            return counted

    def _remember(self, report: RetentionReport) -> None:
        try:
            self._repository.add_run(
                RetentionRun(
                    id=str(uuid.uuid4()),
                    started_at=report.started_at,
                    finished_at=report.finished_at,
                    dry_run=report.dry_run,
                    trigger=report.trigger,
                    counts={
                        category.value: {
                            "items": tally.items,
                            "bytes": tally.bytes,
                            "failed": tally.failed,
                        }
                        for category, tally in report.counts.items()
                    },
                    errors=tuple(report.errors),
                )
            )
        except Exception as exc:
            logger.warning("retention run not recorded (%s)", type(exc).__name__)
