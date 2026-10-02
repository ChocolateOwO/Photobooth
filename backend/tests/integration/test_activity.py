"""Phase 10: what happened at the booth and in Admin, the visits' history and the statistics.

Proven here: a guest's visit is told from Start to the last download, in order, and counted in
History and Statistics; an organizer's changes are recorded by who and on what, never with what
was typed; organizer tests never appear; nothing recorded ever holds a take-home token; and a
record that can not be kept never stops the booth.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from photobooth.container import Container
from photobooth.main import create_delivery_app
from tests.integration.admin_support import USERNAME, adopt_device, device_headers
from tests.integration.test_booth_sessions import SESSIONS, STRIP, activate, booth, start
from tests.integration.test_outputs_delivery import link, reviewing, token_of

ADMIN = "/api/admin"


@pytest.fixture
def guests(container: Container) -> Iterator[TestClient]:
    app = create_delivery_app(container.registry)
    with TestClient(app, base_url="http://192.168.1.50:18113") as client:
        yield client


def types(records: list[dict[str, Any]]) -> list[str]:
    return [record["type"] for record in records]


def test_a_guests_visit_is_told_from_start_to_the_last_download(
    kiosk_client: TestClient, container: Container, guests: TestClient
) -> None:
    device, session = reviewing(kiosk_client, container, STRIP)
    sid = session["id"]
    decoration = {
        "filter": "sepia",
        "stickers": [
            {"sticker": "heart", "output": 1, "x": 0.5, "y": 0.5, "size": 0.3, "rotation": 0}
        ],
    }
    made = kiosk_client.post(
        f"{SESSIONS}/{sid}/render",
        json={"idempotency_key": "render-key-1", "decoration": decoration},
        headers=device,
    )
    assert made.status_code == 200, made.text
    url = link(kiosk_client, device, sid)["url"]
    link(kiosk_client, device, sid)  # a reload shows the same code: no second record
    token = token_of(url)
    assert guests.get(f"/d/{token}").status_code == 200
    assert guests.get(f"/d/{token}").status_code == 200  # opened once, recorded once
    first = made.json()["outputs"][0]["id"]
    assert guests.get(f"/d/{token}/files/{first}?download=1").status_code == 200
    assert guests.get(f"/d/{token}/all.zip").status_code == 200
    assert kiosk_client.post(f"{SESSIONS}/{sid}/give-up", headers=device).status_code == 200

    detail = kiosk_client.get(f"{ADMIN}/history/{sid}", headers=device)
    assert detail.status_code == 200, detail.text
    timeline = detail.json()["timeline"]
    assert types(timeline) == [
        "session_started",
        "frame_chosen",
        *["capture_ok"] * 6,
        "photos_confirmed",
        "render_ok",
        "link_shown",
        "qr_opened",
        "download",
        "download",
        "session_ended",
    ]
    by_type = {record["type"]: record for record in timeline}
    assert by_type["frame_chosen"]["payload"] == {
        "layout": "strip_2x6",
        "captures": 6,
        "outputs": 2,
    }
    assert by_type["render_ok"]["payload"] == {"outputs": 2, "filter": "sepia", "stickers": 1}
    assert by_type["link_shown"]["payload"] == {"renewed": False}
    assert [r["payload"] for r in timeline if r["type"] == "download"] == [
        {"kind": "file", "output": 1},
        {"kind": "zip"},
    ]
    assert by_type["session_ended"]["payload"] == {"state": "completed", "reason": "done"}
    assert {r["actor"] for r in timeline} == {"booth", "guest"}

    visit = detail.json()["visit"]
    assert visit == visit | {
        "state": "completed",
        "layout": "strip_2x6",
        "photos": 6,
        "outputs": 2,
        "filter": "sepia",
        "stickers": 1,
        "link_issued": True,
        "link_opened": True,
        "downloads": 2,
        "profile_name": "Party",
    }

    history = kiosk_client.get(f"{ADMIN}/history", headers=device).json()
    assert history["total"] == 1 and history["visits"][0]["id"] == sid

    stats = kiosk_client.get(f"{ADMIN}/statistics", headers=device).json()
    assert stats == stats | {
        "visits": 1,
        "finished": 1,
        "photos": 6,
        "outputs": 2,
        "decorated": 1,
        "links_opened": 1,
        "downloads": 2,
        "by_layout": [{"key": "strip_2x6", "count": 1}],
        "by_filter": [{"key": "sepia", "count": 1}],
    }
    assert stats["average_minutes"] is not None

    # The guest's key to the photos is nowhere in the database the log lives in.
    container.engine.dispose()
    with sqlite3.connect(container.settings.db_path) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert token.encode() not in container.settings.db_path.read_bytes()


def test_organizer_changes_are_recorded_by_who_and_on_what_never_by_value(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    profile = activate(kiosk_client, admin, name="Secret Garden Party")
    refused = kiosk_client.post(
        f"{ADMIN}/auth/login",
        json={"username": "nobody-real", "password": "a typed secret"},
        headers=device,
    )
    assert refused.status_code == 401
    assert kiosk_client.post(f"{ADMIN}/auth/logout", headers=admin).status_code == 204

    records = container.activity_service.search(_everything(), limit=50)
    assert types([_plain(r) for r in reversed(records)]) == [
        "admin_login",
        "admin_profile_created",
        "admin_profile_activated",
        "admin_login_failed",
        "admin_logout",
    ]
    by_type = {r.type.value: r for r in records}
    assert by_type["admin_profile_created"].payload == {"target": profile["id"]}
    assert by_type["admin_profile_created"].profile_id == profile["id"]
    assert by_type["admin_profile_activated"].admin_username == USERNAME
    assert by_type["admin_login_failed"].admin_username is None  # never the name typed
    assert by_type["admin_login_failed"].payload == {"reason": "refused"}
    with sqlite3.connect(container.settings.db_path) as conn:
        rows = " ".join(str(row) for row in conn.execute("SELECT * FROM activity_log"))
    for typed in ("Secret Garden Party", "nobody-real", "a typed secret", "correct horse"):
        assert typed not in rows


def test_an_organizers_test_visit_is_never_a_guests_visit(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    profile = activate(kiosk_client, admin)
    started = kiosk_client.post(
        f"{ADMIN}/booth-test/sessions",
        json={"idempotency_key": "test-visit-1", "profile_id": profile["id"]},
        headers=admin,
    )
    assert started.status_code == 201, started.text
    records = container.activity_service.search(_everything(), limit=50)
    assert "admin_test_started" in {r.type.value for r in records}
    assert all(r.session_id is None for r in records)  # nothing about the test visit itself
    assert kiosk_client.get(f"{ADMIN}/history", headers=device).json()["total"] == 0
    assert kiosk_client.get(f"{ADMIN}/statistics", headers=device).json()["visits"] == 0


def test_history_filters_and_pages_the_visits(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin)
    for n in range(3):
        visit = start(kiosk_client, device, key=f"start-key-{n}")
        if n < 2:
            kiosk_client.post(f"{SESSIONS}/{visit['id']}/give-up", headers=device)
    page = kiosk_client.get(f"{ADMIN}/history?limit=2", headers=device).json()
    assert page["total"] == 3 and len(page["visits"]) == 2
    assert [v["state"] for v in page["visits"]] == ["eligibility_ok", "cancelled"]
    rest = kiosk_client.get(f"{ADMIN}/history?limit=2&offset=2", headers=device).json()
    assert [v["state"] for v in rest["visits"]] == ["cancelled"]
    left = kiosk_client.get(f"{ADMIN}/history?state=cancelled", headers=device).json()
    assert left["total"] == 2
    later = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    assert (
        kiosk_client.get(f"{ADMIN}/history", params={"since": later}, headers=device).json()[
            "total"
        ]
        == 0
    )
    stats = kiosk_client.get(f"{ADMIN}/statistics", headers=device).json()
    assert stats == stats | {"visits": 3, "cancelled": 2, "in_progress": 1, "finished": 0}
    bad = kiosk_client.get(
        f"{ADMIN}/history", params={"since": later, "until": later}, headers=device
    )
    assert bad.status_code == 422


def test_the_activity_log_pages_newest_first_and_filters_by_who(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin)
    start(kiosk_client, device)
    first = kiosk_client.get(f"{ADMIN}/activity?limit=2", headers=device).json()
    assert len(first["records"]) == 2 and first["more"] is True
    assert first["records"][0]["type"] == "session_started"  # the newest
    last = first["records"][-1]
    second = kiosk_client.get(
        f"{ADMIN}/activity",
        params={"limit": 50, "before_at": last["at"], "before_id": last["id"]},
        headers=device,
    ).json()
    assert second["more"] is False
    seen = [r["id"] for r in first["records"] + second["records"]]
    assert len(seen) == len(set(seen)) == 4  # login, created, activated, started
    booth_only = kiosk_client.get(f"{ADMIN}/activity?actor=booth", headers=device).json()
    assert types(booth_only["records"]) == ["session_started"]


def test_history_and_statistics_need_an_organizer(
    kiosk_client: TestClient, container: Container
) -> None:
    device = device_headers(adopt_device(kiosk_client, container))
    for path in ("activity", "history", "statistics"):
        assert kiosk_client.get(f"{ADMIN}/{path}", headers=device).status_code == 401, path


def test_a_visit_that_times_out_is_recorded_once(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin)
    visit = start(kiosk_client, device)
    with sqlite3.connect(container.settings.db_path) as conn:
        conn.execute(
            "UPDATE booth_sessions SET last_activity_at = ? WHERE id = ?",
            (
                (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S.%f"),
                visit["id"],
            ),
        )
    assert container.session_service.close_inactive() == [visit["id"]]
    assert container.session_service.close_inactive() == []
    timeline = kiosk_client.get(f"{ADMIN}/history/{visit['id']}", headers=device).json()
    assert types(timeline["timeline"]) == ["session_started", "reset_timeout"]
    assert timeline["timeline"][-1]["actor"] == "system"
    assert timeline["visit"]["state"] == "abandoned"


def test_a_record_that_can_not_be_kept_never_stops_the_booth(
    kiosk_client: TestClient, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin)

    def broken(_record: Any) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(container.activity_service._repository, "add", broken)
    visit = start(kiosk_client, device)
    assert visit["state"] == "eligibility_ok"


def test_a_new_link_after_a_restart_is_recorded_as_renewed(
    kiosk_client: TestClient, container: Container
) -> None:
    device, session = reviewing(kiosk_client, container, STRIP)
    sid = session["id"]
    made = kiosk_client.post(
        f"{SESSIONS}/{sid}/render", json={"idempotency_key": "render-key-1"}, headers=device
    )
    assert made.status_code == 200
    link(kiosk_client, device, sid)
    container.delivery_service._plaintext.clear()  # what a restart forgets
    link(kiosk_client, device, sid)
    timeline = kiosk_client.get(f"{ADMIN}/history/{sid}", headers=device).json()["timeline"]
    assert [r["payload"] for r in timeline if r["type"] == "link_shown"] == [
        {"renewed": False},
        {"renewed": True},
    ]


# ---- inspection fixes (P10-R1 .. R6) ----------------------------------------------------------


def test_a_guest_gets_their_photos_even_when_the_record_can_not_be_kept(
    kiosk_client: TestClient,
    container: Container,
    guests: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P10-R1: a failing lookup inside the link recorder never turns a download into a 404."""
    device, session = reviewing(kiosk_client, container, STRIP)
    made = kiosk_client.post(
        f"{SESSIONS}/{session['id']}/render",
        json={"idempotency_key": "render-key-1"},
        headers=device,
    )
    assert made.status_code == 200
    token = token_of(link(kiosk_client, device, session["id"])["url"])

    def broken(_session_id: str) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(container.session_repository, "get", broken)
    assert guests.get(f"/d/{token}").status_code == 200
    assert guests.get(f"/d/{token}/all.zip").status_code == 200


def test_a_render_settled_after_the_fact_is_recorded_once(
    kiosk_client: TestClient, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P10-R2: the finishing step failed; the render settled at the next read counts once."""
    device, session = reviewing(kiosk_client, container, STRIP)
    who = _device_of(kiosk_client, container)
    repository = container.session_service._repository
    real = repository.finalize_render
    calls = {"n": 0}

    def flaky(operation_id: str, fingerprint: str) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database went away for a moment")
        return real(operation_id, fingerprint)

    monkeypatch.setattr(repository, "finalize_render", flaky)
    with pytest.raises(RuntimeError):
        container.session_service.render(who, session["id"], "render-a-key", {"filter": "mono"})
    assert kiosk_client.get(f"{SESSIONS}/current", headers=device).json()["state"] == "delivered"
    kiosk_client.get(f"{SESSIONS}/current", headers=device)  # settled once, recorded once
    timeline = kiosk_client.get(f"{ADMIN}/history/{session['id']}", headers=device).json()
    rendered = [r for r in timeline["timeline"] if r["type"] == "render_ok"]
    assert [r["payload"] for r in rendered] == [{"outputs": 2, "filter": "mono", "stickers": 0}]


def test_a_photo_that_could_not_be_stored_is_recorded_and_its_retry_is_no_retake(
    kiosk_client: TestClient, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P10-R2 / P10-R3."""
    from tests.integration.test_booth_sessions import PRINT34, choose, send

    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"])
    visit = start(kiosk_client, device)
    choose(kiosk_client, device, visit["id"], PRINT34)
    files = container.session_service._files
    real_put = files.put
    calls = {"n": 0}

    def flaky(key: str, data: bytes) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full for a moment")
        real_put(key, data)

    monkeypatch.setattr(files, "put", flaky)
    with pytest.raises(OSError):
        send(kiosk_client, device, visit["id"], 1)
    assert send(kiosk_client, device, visit["id"], 1, attempt=2).status_code == 200
    detail = kiosk_client.get(f"{ADMIN}/history/{visit['id']}", headers=device).json()
    failed = [r for r in detail["timeline"] if r["type"] == "capture_failed"]
    assert [r["payload"] for r in failed] == [
        {"shot": 1, "attempt": 1, "reason": "file_not_stored"}
    ]
    assert detail["visit"]["retakes"] == 0  # a retried upload is not a retake


def test_a_full_page_of_activity_still_says_more_follow(
    kiosk_client: TestClient, container: Container
) -> None:
    """P10-R5."""
    from photobooth.modules.activity.domain import ActivityType

    _admin, device = booth(kiosk_client, container)
    for _ in range(205):
        container.activity_service.record(ActivityType.ADMIN_TESTS_CLEARED, admin_username="a")
    page = kiosk_client.get(f"{ADMIN}/activity?limit=200", headers=device).json()
    assert len(page["records"]) == 200 and page["more"] is True


@pytest.mark.parametrize("path", ["history", "statistics", "activity"])
def test_a_time_without_a_time_zone_is_refused_not_a_crash(
    kiosk_client: TestClient, container: Container, path: str
) -> None:
    """P10-R6."""
    _admin, device = booth(kiosk_client, container)
    answer = kiosk_client.get(
        f"{ADMIN}/{path}", params={"since": "2026-10-02T00:00:00"}, headers=device
    )
    assert answer.status_code == 422


def _device_of(client: TestClient, container: Container) -> str:
    from tests.integration.test_outputs_delivery import device_id

    return device_id(client, container)


def _everything() -> Any:
    from photobooth.modules.activity.domain import ActivityFilter

    return ActivityFilter()


def _plain(record: Any) -> dict[str, Any]:
    return {"type": record.type.value}
