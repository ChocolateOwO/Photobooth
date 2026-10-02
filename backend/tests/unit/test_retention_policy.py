"""The retention policy's own rules."""

from __future__ import annotations

from photobooth.modules.retention.domain import MetadataMode, RetentionPolicy


def test_the_provisional_defaults_are_a_valid_policy() -> None:
    policy = RetentionPolicy()
    assert policy.problems() == []
    assert (policy.originals_days, policy.outputs_days, policy.link_days, policy.temp_hours) == (
        7,
        30,
        7,
        24,
    )
    assert policy.metadata_mode is MetadataMode.KEEP


def test_a_link_never_outlives_its_photos_and_visits_never_go_before_them() -> None:
    assert RetentionPolicy(link_days=31).problems() == [
        "the take-home link can not outlive the finished photos"
    ]
    assert RetentionPolicy(metadata_mode=MetadataMode.DELETE, metadata_days=29).problems() == [
        "visits can not be anonymized or deleted before their photos are"
    ]
    # Kept visits have no deadline of their own.
    assert RetentionPolicy(metadata_mode=MetadataMode.KEEP, metadata_days=1).problems() == []


def test_every_period_has_bounds() -> None:
    assert RetentionPolicy(originals_days=0).problems() == ["originals_days must be 1 to 3650 days"]
    assert RetentionPolicy(backup_days=3651).problems() == ["backup_days must be 1 to 3650 days"]
    assert RetentionPolicy(temp_hours=0).problems() == ["temp_hours must be 1 to 720 hours"]
