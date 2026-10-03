"""The retention rules: a named policy per event, and the booth's own housekeeping."""

from __future__ import annotations

from photobooth.modules.retention.domain import Housekeeping, MetadataMode, RetentionPolicy
from photobooth.modules.sessions.domain import VisitRetention


def test_the_provisional_defaults_are_valid() -> None:
    policy = RetentionPolicy()
    assert policy.problems() == []
    assert (policy.originals_days, policy.outputs_days, policy.link_days) == (7, 30, 7)
    assert policy.metadata_mode is MetadataMode.KEEP
    house = Housekeeping()
    assert house.problems() == []
    assert (house.temp_hours, house.activity_log_days, house.backup_days) == (24, 90, 7)
    # A visit frozen without a policy (never after migration 0012) keeps the same defaults.
    frozen = VisitRetention()
    assert (frozen.originals_days, frozen.outputs_days, frozen.link_days) == (7, 30, 7)


def test_a_link_never_outlives_its_photos_and_visits_never_go_before_them() -> None:
    assert RetentionPolicy(link_days=31).problems() == [
        "the take-home link can not outlive the finished photos"
    ]
    assert RetentionPolicy(metadata_mode=MetadataMode.DELETE, metadata_days=29).problems() == [
        "visits can not be anonymized or deleted before their photos are"
    ]
    # Kept visits have no deadline of their own.
    assert RetentionPolicy(metadata_mode=MetadataMode.KEEP, metadata_days=1).problems() == []


def test_every_period_has_bounds_and_a_policy_a_name() -> None:
    assert RetentionPolicy(originals_days=0).problems() == ["originals_days must be 1 to 3650 days"]
    assert RetentionPolicy(name="  ").problems() == ["a policy needs a name"]
    assert RetentionPolicy(name="x" * 61).problems() == ["a policy name has at most 60 characters"]
    assert Housekeeping(backup_days=3651).problems() == ["backup_days must be 1 to 3650 days"]
    assert Housekeeping(temp_hours=0).problems() == ["temp_hours must be 1 to 720 hours"]


def test_a_visit_knows_when_each_part_of_it_goes() -> None:
    frozen = VisitRetention(originals_days=2, outputs_days=9, records_days=40)
    assert frozen.days("originals") == 2
    assert frozen.days("outputs") == 9
    assert frozen.days("anonymize") == frozen.days("delete") == 40
