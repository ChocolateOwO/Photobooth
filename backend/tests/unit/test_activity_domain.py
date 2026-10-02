"""An activity record keeps only allowlisted plain facts: never a path, link, text or secret."""

from __future__ import annotations

from photobooth.modules.activity.domain import ACTOR_OF, PAYLOAD_KEYS, ActivityType, Actor, clean


def test_only_the_keys_a_type_allows_are_kept() -> None:
    kept = clean(
        ActivityType.CAPTURE_FAILED,
        {"shot": 2, "attempt": 1, "reason": "refused", "password": "x", "path": "C:/x"},
    )
    assert kept == {"shot": 2, "attempt": 1, "reason": "refused"}


def test_values_are_short_plain_words_numbers_and_flags() -> None:
    kept = clean(
        ActivityType.ADMIN_PROFILE_UPDATED,
        {"target": "6f1c2d3e-4b5a-4c6d-8e7f-90a1b2c3d4e5"},
    )
    assert kept == {"target": "6f1c2d3e-4b5a-4c6d-8e7f-90a1b2c3d4e5"}
    for unsafe in (
        "two words",
        "http://192.168.1.20:8113/d/abc",
        "E:/photos/a.jpg",
        "x" * 65,
        "ไทย",
        "",
        "a\nb",
    ):
        assert clean(ActivityType.ADMIN_PROFILE_UPDATED, {"target": unsafe}) == {}
    assert clean(ActivityType.RENDER_OK, {"outputs": 10**9}) == {}
    assert clean(ActivityType.RENDER_OK, {"outputs": 2.5}) == {}
    assert clean(ActivityType.LINK_SHOWN, {"renewed": True}) == {"renewed": True}


def test_every_type_has_its_keys_and_its_actor() -> None:
    assert set(PAYLOAD_KEYS) == set(ActivityType)
    assert set(ACTOR_OF) == set(ActivityType)
    assert ACTOR_OF[ActivityType.DOWNLOAD] is Actor.GUEST
    assert ACTOR_OF[ActivityType.RESET_TIMEOUT] is Actor.SYSTEM
    assert ACTOR_OF[ActivityType.ADMIN_LOGIN_FAILED] is Actor.ADMIN
    assert ACTOR_OF[ActivityType.CAPTURE_OK] is Actor.BOOTH
    # No type may carry anything that could hold a token, a name or typed text.
    for keys in PAYLOAD_KEYS.values():
        assert not keys & {"token", "url", "name", "username", "password", "path", "ip", "text"}
