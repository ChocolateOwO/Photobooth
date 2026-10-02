"""Phase 11: retention. The booth deletes what is past its time, and nothing else, ever.

Proven here: a dry run counts and changes nothing; a real cleanup deletes the camera's photos and
the finished photos of visits that are over (their links stop), makes visits anonymous or deletes
them with everything about them, trims the activity log, temporary files, old backups (never the
newest) and rotated logs, and never touches a visit still going or anything outside this instance;
deleting needs an explicit confirmation; a deleted event can be deleted for good with its visits;
the schedule runs at most once an hour; and the startup cleanup removes again whatever a restored
older backup brought back.
"""

from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from photobooth.cli import prepare_retention
from photobooth.container import Container
from photobooth.main import create_delivery_app
from photobooth.modules.retention.domain import (
    MetadataMode,
    RetentionError,
    RetentionPolicy,
    Trigger,
)
from photobooth.modules.storage.domain import StorageKey
from tests.integration.admin_support import CSRF_HEADER
from tests.integration.test_booth_sessions import (
    PRINT34,
    SESSIONS,
    activate,
    booth,
    choose,
    send,
    start,
)
from tests.integration.test_outputs_delivery import link, reviewing, token_of

ADMIN = "/api/admin/retention"
DELETE = {"dry_run": False, "confirm": "DELETE"}


@pytest.fixture
def guests(container: Container) -> Iterator[TestClient]:
    app = create_delivery_app(container.registry)
    with TestClient(app, base_url="http://192.168.1.50:18113") as client:
        yield client


def finished_visit(client: TestClient, container: Container) -> tuple[dict[str, str], str, str]:
    """A guest's visit that is over: photos taken, finished photos made, link shown, Done."""
    device, session = reviewing(client, container, PRINT34)
    made = client.post(
        f"{SESSIONS}/{session['id']}/render",
        json={"idempotency_key": "render-key-1"},
        headers=device,
    )
    assert made.status_code == 200, made.text
    token = token_of(link(client, device, session["id"])["url"])
    assert client.post(f"{SESSIONS}/{session['id']}/give-up", headers=device).status_code == 200
    return device, session["id"], token


def later(container: Container, days: float) -> None:
    """Retention sees the booth's clock `days` ahead."""
    moment = datetime.now(UTC) + timedelta(days=days)
    container.retention_service._clock = lambda: moment


def stored(container: Container, kind: str, session_id: str) -> list[bool]:
    """Whether each photo ("captures") or finished photo ("outputs") of a visit is on disk."""
    table = "capture_assets" if kind == "captures" else "output_assets"
    with sqlite3.connect(container.settings.db_path) as conn:
        keys = [
            row[0]
            for row in conn.execute(
                f"SELECT storage_key FROM {table} WHERE session_id = ? AND status = 'ok'",  # noqa: S608
                (session_id,),
            )
        ]
    return [container.storage.exists(StorageKey(key)) for key in keys]


def counts(report: Any) -> dict[str, int]:
    return {row["category"]: row["items"] for row in report["counts"]}


# ---- the cleanup -----------------------------------------------------------------------------


def test_a_dry_run_counts_and_a_confirmed_run_deletes_photos_past_their_time(
    kiosk_client: TestClient, container: Container, guests: TestClient
) -> None:
    device, sid, token = finished_visit(kiosk_client, container)
    assert all(stored(container, "captures", sid)) and all(stored(container, "outputs", sid))

    later(container, 10)  # originals (7 days) are due, finished photos (30 days) are not
    dry = kiosk_client.post(
        f"{ADMIN}/run", json={"dry_run": True}, headers=organizer(kiosk_client, device)
    )
    assert dry.status_code == 200, dry.text
    assert counts(dry.json()) | {"originals": 2, "outputs": 0} == counts(dry.json())
    assert all(stored(container, "captures", sid))  # a dry run changes nothing

    done = kiosk_client.post(f"{ADMIN}/run", json=DELETE, headers=organizer(kiosk_client, device))
    assert done.status_code == 200 and counts(done.json())["originals"] == 2
    assert not any(stored(container, "captures", sid))
    assert all(stored(container, "outputs", sid))
    assert guests.get(f"/d/{token}").status_code == 200  # the guest still has their photos

    later(container, 40)
    done = kiosk_client.post(f"{ADMIN}/run", json=DELETE, headers=organizer(kiosk_client, device))
    assert counts(done.json())["outputs"] == 1
    assert not any(stored(container, "outputs", sid))
    assert guests.get(f"/d/{token}").status_code == 404  # the link stops with the photos
    again = kiosk_client.post(f"{ADMIN}/run", json=DELETE, headers=organizer(kiosk_client, device))
    assert counts(again.json())["originals"] == counts(again.json())["outputs"] == 0

    # The visit is still listed (its counts and times), and every run is on record.
    history = kiosk_client.get("/api/admin/history", headers=device).json()
    assert [v["id"] for v in history["visits"]] == [sid]
    runs = kiosk_client.get(f"{ADMIN}/runs", headers=device).json()
    assert sorted((r["trigger"], r["dry_run"]) for r in runs) == [("manual", False)] * 3 + [
        ("manual", True)
    ]


def test_a_visit_still_going_is_never_touched(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"])
    visit = start(kiosk_client, device)
    choose(kiosk_client, device, visit["id"], PRINT34)
    assert send(kiosk_client, device, visit["id"], 1).status_code == 200
    later(container, 400)
    service = container.retention_service
    service.update_policy(
        RetentionPolicy(metadata_mode=MetadataMode.DELETE, metadata_days=60),
        service.policy().revision,
    )
    report = container.retention_service.run(Trigger.MANUAL, dry_run=False)
    assert report.errors == ()
    assert all(stored(container, "captures", visit["id"]))
    assert container.session_repository.get(visit["id"]) is not None


@pytest.mark.parametrize("mode", [MetadataMode.ANONYMIZE, MetadataMode.DELETE])
def test_visit_records_are_made_anonymous_or_deleted_with_everything_about_them(
    kiosk_client: TestClient, container: Container, mode: MetadataMode
) -> None:
    device, sid, _token = finished_visit(kiosk_client, container)
    service = container.retention_service
    policy = service.policy()
    service.update_policy(RetentionPolicy(metadata_mode=mode, metadata_days=45), policy.revision)
    later(container, 50)
    report = service.run(Trigger.MANUAL, dry_run=False)
    with sqlite3.connect(container.settings.db_path) as conn:
        visit = conn.execute(
            "SELECT device_id, eligibility_result FROM booth_sessions WHERE id = ?", (sid,)
        ).fetchone()
        left = {
            table: conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE session_id = ?",  # noqa: S608
                (sid,),
            ).fetchone()[0]
            for table in ("capture_assets", "output_assets", "delivery_tokens", "activity_log")
        }
    tallies = {category.value: tally.items for category, tally in report.counts.items()}
    if mode is MetadataMode.ANONYMIZE:
        assert tallies["visits_anonymized"] == 1
        assert visit == ("anonymous", None)
        assert left["capture_assets"] > 0  # the record stays, without its device
    else:
        assert tallies["visits_deleted"] == 1
        assert visit is None
        assert left == {
            "capture_assets": 0,
            "output_assets": 0,
            "delivery_tokens": 0,
            "activity_log": 0,
        }
    assert kiosk_client.get("/api/admin/history", headers=device).json()["total"] == (
        1 if mode is MetadataMode.ANONYMIZE else 0
    )


def test_old_activity_temp_files_backups_and_logs_go_and_nothing_else(
    kiosk_client: TestClient, container: Container, tmp_path: Path
) -> None:
    _admin, device = booth(kiosk_client, container)
    settings = container.settings
    month_ago = time.time() - 30 * 24 * 3600

    def file(path: Path, old: bool = True) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 10)
        if old:
            os.utime(path, (month_ago, month_ago))
        return path

    temp = file(settings.storage_dir / "captures" / "s" / ".a.jpg.0123456789ab.tmp")
    keep_temp = file(settings.storage_dir / "captures" / "s" / ".b.jpg.0123456789ab.tmp", old=False)
    photo = file(settings.storage_dir / "captures" / "s" / "photo.jpg")  # not a temp file
    old_backup = file(settings.backups_dir / "dummy-20260901T000000Z-aaaaaa-0010.sqlite")
    newest = file(settings.backups_dir / "dummy-20260902T000000Z-bbbbbb-0010.sqlite")
    os.utime(newest, (month_ago + 60, month_ago + 60))  # old too, but the newest: it stays
    rotated = file(settings.logs_dir / "photobooth.log.1")
    current = file(settings.logs_dir / "photobooth.log")
    outside = file(tmp_path / "elsewhere" / ".c.jpg.0123456789ab.tmp")
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO activity_log (id, at, type, actor, payload) "
            "VALUES ('old', '2020-01-01 00:00:00.000000', 'admin_login', 'admin', '{}')"
        )

    done = kiosk_client.post(
        f"{ADMIN}/run", json=DELETE, headers=organizer(kiosk_client, device)
    ).json()
    found = counts(done)
    assert found["temp"] == 1 and found["backups"] == 1 and found["app_logs"] == 1
    assert found["activity"] >= 1
    assert not temp.exists() and not old_backup.exists() and not rotated.exists()
    for kept in (keep_temp, photo, newest, current, outside):
        assert kept.exists(), kept


def test_retention_only_works_inside_its_own_instance(container: Container, tmp_path: Path) -> None:
    from photobooth.modules.retention.files import InstanceFolders

    settings = container.settings
    with pytest.raises(RetentionError):
        InstanceFolders(
            settings.instance_root, tmp_path, settings.backups_dir, settings.logs_dir, set().clear
        )
    with pytest.raises(RetentionError):
        InstanceFolders(
            settings.instance_root,
            settings.storage_dir,
            settings.instance_root,
            settings.logs_dir,
            set().clear,
        )


# ---- the policy and the confirmation ---------------------------------------------------------


def test_the_policy_is_checked_and_saved_once(
    kiosk_client: TestClient, container: Container
) -> None:
    _admin, device = booth(kiosk_client, container)
    current = kiosk_client.get(f"{ADMIN}/policy", headers=device).json()
    assert current == current | {
        "originals_days": 7,
        "outputs_days": 30,
        "link_days": 7,
        "temp_hours": 24,
        "metadata_mode": "keep",
        "revision": 1,
    }
    body = {k: v for k, v in current.items() if k != "updated_at"}
    admin_headers = organizer(kiosk_client, device)
    bad = kiosk_client.put(f"{ADMIN}/policy", json=body | {"link_days": 40}, headers=admin_headers)
    assert bad.status_code == 422
    early = kiosk_client.put(
        f"{ADMIN}/policy",
        json=body | {"metadata_mode": "delete", "metadata_days": 10},
        headers=admin_headers,
    )
    assert early.status_code == 422  # visits never go before their photos
    saved = kiosk_client.put(f"{ADMIN}/policy", json=body | {"link_days": 3}, headers=admin_headers)
    assert saved.status_code == 200 and saved.json()["revision"] == 2
    stale = kiosk_client.put(f"{ADMIN}/policy", json=body, headers=admin_headers)
    assert stale.status_code == 409
    lifetime = container.delivery_service._policy.lifetime()
    assert lifetime == timedelta(days=3)  # new take-home links follow the policy


def test_deleting_needs_the_word_delete_and_an_organizer(
    kiosk_client: TestClient, container: Container
) -> None:
    _admin, device = booth(kiosk_client, container)
    headers = organizer(kiosk_client, device)
    refused = kiosk_client.post(f"{ADMIN}/run", json={"dry_run": False}, headers=headers)
    assert refused.status_code == 422
    wrong = kiosk_client.post(
        f"{ADMIN}/run", json={"dry_run": False, "confirm": "yes"}, headers=headers
    )
    assert wrong.status_code == 422
    assert kiosk_client.post("/api/admin/auth/logout", headers=headers).status_code == 204
    assert kiosk_client.get(f"{ADMIN}/policy", headers=device).status_code == 401


# ---- deleting an event for good ----------------------------------------------------------------


def test_a_deleted_event_is_deleted_for_good_with_its_visits(
    kiosk_client: TestClient, container: Container
) -> None:
    device, sid, _token = finished_visit(kiosk_client, container)
    profile = container.session_repository.get(sid)
    assert profile is not None
    pid = profile.event_profile_id
    headers = organizer(kiosk_client, device)
    live = kiosk_client.post(
        f"{ADMIN}/events/{pid}/remove", json={"dry_run": True}, headers=headers
    )
    assert live.status_code == 409  # only a deleted event

    with sqlite3.connect(container.settings.db_path) as conn:
        conn.execute(
            "UPDATE event_profiles SET is_active = 0, deleted_at = '2026-10-01 00:00:00.000000' "
            "WHERE id = ?",
            (pid,),
        )
    dry = kiosk_client.post(f"{ADMIN}/events/{pid}/remove", json={"dry_run": True}, headers=headers)
    assert dry.status_code == 200 and dry.json()["visits"] == 1
    assert container.session_repository.get(sid) is not None
    done = kiosk_client.post(f"{ADMIN}/events/{pid}/remove", json=DELETE, headers=headers)
    assert done.status_code == 200, done.text
    assert container.session_repository.get(sid) is None
    assert kiosk_client.get(f"/api/admin/profiles/{pid}", headers=device).status_code == 404
    unknown = kiosk_client.post(
        f"{ADMIN}/events/{pid}/remove", json={"dry_run": True}, headers=headers
    )
    assert unknown.status_code == 404


# ---- the schedule and the startup cleanup ------------------------------------------------------


def test_the_schedule_runs_at_most_once_an_hour(container: Container) -> None:
    assert container.retention_service.scheduled() is not None
    assert container.retention_service.scheduled() is None
    later(container, 0.1)  # 2.4 hours on
    assert container.retention_service.scheduled() is not None


def test_the_startup_cleanup_removes_what_a_restored_backup_brought_back(
    kiosk_client: TestClient, container: Container, guests: TestClient
) -> None:
    _device, sid, token = finished_visit(kiosk_client, container)
    later(container, 40)
    container.retention_service.run(Trigger.MANUAL, dry_run=False)
    assert not any(stored(container, "outputs", sid))
    # An older backup is restored: its rows still say the files exist and the link works.
    with sqlite3.connect(container.settings.db_path) as conn:
        conn.execute(
            "UPDATE capture_assets SET file_deleted_at = NULL WHERE session_id = ?", (sid,)
        )
        conn.execute("UPDATE output_assets SET file_deleted_at = NULL WHERE session_id = ?", (sid,))
        conn.execute("UPDATE delivery_tokens SET revoked_at = NULL WHERE session_id = ?", (sid,))
    later(container, 41)
    prepare_retention(container)  # what `serve` does before the booth opens
    with sqlite3.connect(container.settings.db_path) as conn:
        undeleted = conn.execute(
            "SELECT COUNT(*) FROM output_assets WHERE session_id = ? AND file_deleted_at IS NULL",
            (sid,),
        ).fetchone()[0]
        live = conn.execute(
            "SELECT COUNT(*) FROM delivery_tokens WHERE session_id = ? AND revoked_at IS NULL",
            (sid,),
        ).fetchone()[0]
    assert undeleted == 0 and live == 0
    assert guests.get(f"/d/{token}").status_code == 404
    runs = container.retention_service.runs()
    assert runs[0].trigger is Trigger.STARTUP and not runs[0].dry_run


def organizer(client: TestClient, device: dict[str, str]) -> dict[str, str]:
    """The device headers plus the CSRF header of the organizer signed in on this client."""
    session = client.get("/api/admin/auth/session", headers=device)
    assert session.status_code == 200, session.text
    return {**device, CSRF_HEADER: session.json()["csrf_token"]}
