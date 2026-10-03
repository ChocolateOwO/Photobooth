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

import contextlib
import os
import sqlite3
import time
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from photobooth.cli import prepare_retention
from photobooth.container import Container
from photobooth.main import create_delivery_app
from photobooth.modules.event_profiles.domain import ProfileSettings
from photobooth.modules.retention.domain import (
    STANDARD_POLICY_ID,
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
REMOVE = {"dry_run": False, "confirm": "DELETE"}


def confirmed(container: Container) -> dict[str, Any]:
    """A confirmed cleanup, under the housekeeping settings the organizer has seen."""
    return REMOVE | {"housekeeping_revision": container.retention_service.housekeeping().revision}


def standard(container: Container, **changes: Any) -> None:
    """Change the default policy (only visits that start afterwards follow it)."""
    service = container.retention_service
    current = service.policy(STANDARD_POLICY_ID)
    service.update_policy(STANDARD_POLICY_ID, replace(current, **changes), current.revision)


@pytest.fixture
def guests(container: Container) -> Iterator[TestClient]:
    app = create_delivery_app(container.registry)
    with TestClient(app, base_url="http://192.168.1.50:18113") as client:
        yield client


def finished_visit(
    client: TestClient, container: Container, **profile: Any
) -> tuple[dict[str, str], str, str]:
    """A guest's visit that is over: photos taken, finished photos made, link shown, Done."""
    device, session = reviewing(client, container, PRINT34, **profile)
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

    done = kiosk_client.post(
        f"{ADMIN}/run", json=confirmed(container), headers=organizer(kiosk_client, device)
    )
    assert done.status_code == 200 and counts(done.json())["originals"] == 2
    assert not any(stored(container, "captures", sid))
    assert all(stored(container, "outputs", sid))
    assert guests.get(f"/d/{token}").status_code == 200  # the guest still has their photos

    later(container, 40)
    done = kiosk_client.post(
        f"{ADMIN}/run", json=confirmed(container), headers=organizer(kiosk_client, device)
    )
    assert counts(done.json())["outputs"] == 1
    assert not any(stored(container, "outputs", sid))
    assert guests.get(f"/d/{token}").status_code == 404  # the link stops with the photos
    again = kiosk_client.post(
        f"{ADMIN}/run", json=confirmed(container), headers=organizer(kiosk_client, device)
    )
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
    standard(container, metadata_mode=MetadataMode.DELETE, metadata_days=60)
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"])
    visit = start(kiosk_client, device)
    choose(kiosk_client, device, visit["id"], PRINT34)
    assert send(kiosk_client, device, visit["id"], 1).status_code == 200
    later(container, 400)
    report = container.retention_service.run(Trigger.MANUAL, dry_run=False)
    assert report.errors == ()
    assert all(stored(container, "captures", visit["id"]))
    assert container.session_repository.get(visit["id"]) is not None


@pytest.mark.parametrize("mode", [MetadataMode.ANONYMIZE, MetadataMode.DELETE])
def test_visit_records_are_made_anonymous_or_deleted_with_everything_about_them(
    kiosk_client: TestClient, container: Container, mode: MetadataMode
) -> None:
    standard(container, metadata_mode=mode, metadata_days=45)
    device, sid, _token = finished_visit(kiosk_client, container)
    service = container.retention_service
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
    launcher = file(settings.logs_dir / "backend-console.out.log")  # held open by the launcher
    current = file(settings.logs_dir / "photobooth.log")
    outside = file(tmp_path / "elsewhere" / ".c.jpg.0123456789ab.tmp")
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO activity_log (id, at, type, actor, payload) "
            "VALUES ('old', '2020-01-01 00:00:00.000000', 'admin_login', 'admin', '{}')"
        )

    done = kiosk_client.post(
        f"{ADMIN}/run", json=confirmed(container), headers=organizer(kiosk_client, device)
    ).json()
    found = counts(done)
    assert found["temp"] == 1 and found["backups"] == 1 and found["app_logs"] == 1
    assert found["activity"] >= 1
    assert not temp.exists() and not old_backup.exists() and not rotated.exists()
    for kept in (keep_temp, photo, newest, current, outside, launcher):
        assert kept.exists(), kept


def test_retention_only_works_inside_its_own_instance(container: Container, tmp_path: Path) -> None:
    from photobooth.modules.retention.files import InstanceFolders

    settings = container.settings
    with pytest.raises(RetentionError):
        InstanceFolders(
            settings.instance_root, tmp_path, settings.backups_dir, settings.logs_dir, list().clear
        )
    with pytest.raises(RetentionError):
        InstanceFolders(
            settings.instance_root,
            settings.storage_dir,
            settings.instance_root,
            settings.logs_dir,
            list().clear,
        )


# ---- the policy and the confirmation ---------------------------------------------------------


POLICY_FIELDS = (
    "name",
    "originals_days",
    "outputs_days",
    "link_days",
    "metadata_mode",
    "metadata_days",
    "revision",
)


def body_of(policy: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {k: policy[k] for k in POLICY_FIELDS} | changes


def test_a_policy_is_checked_and_saved_once(kiosk_client: TestClient, container: Container) -> None:
    _admin, device = booth(kiosk_client, container)
    listed = kiosk_client.get(f"{ADMIN}/policies", headers=device).json()
    assert len(listed) == 1
    current = listed[0]
    assert current == current | {
        "id": STANDARD_POLICY_ID,
        "name": "Standard",
        "originals_days": 7,
        "outputs_days": 30,
        "link_days": 7,
        "metadata_mode": "keep",
        "is_default": True,
        "revision": 1,
    }
    url = f"{ADMIN}/policies/{STANDARD_POLICY_ID}"
    headers = organizer(kiosk_client, device)
    bad = kiosk_client.put(url, json=body_of(current, link_days=40), headers=headers)
    assert bad.status_code == 422  # the link can not outlive the finished photos
    early = kiosk_client.put(
        url, json=body_of(current, metadata_mode="delete", metadata_days=10), headers=headers
    )
    assert early.status_code == 422  # visits never go before their photos
    saved = kiosk_client.put(url, json=body_of(current, link_days=3), headers=headers)
    assert saved.status_code == 200 and saved.json()["revision"] == 2
    stale = kiosk_client.put(url, json=body_of(current), headers=headers)
    assert stale.status_code == 409


def test_the_housekeeping_settings_are_checked_and_saved_once(
    kiosk_client: TestClient, container: Container
) -> None:
    _admin, device = booth(kiosk_client, container)
    current = kiosk_client.get(f"{ADMIN}/housekeeping", headers=device).json()
    assert current == current | {
        "temp_hours": 24,
        "activity_log_days": 90,
        "backup_days": 7,
        "app_log_days": 14,
    }
    body = {k: v for k, v in current.items() if k != "updated_at"}
    headers = organizer(kiosk_client, device)
    assert (
        kiosk_client.put(
            f"{ADMIN}/housekeeping", json=body | {"temp_hours": 0}, headers=headers
        ).status_code
        == 422
    )
    saved = kiosk_client.put(
        f"{ADMIN}/housekeeping", json=body | {"backup_days": 3}, headers=headers
    )
    assert saved.status_code == 200 and saved.json()["revision"] == body["revision"] + 1
    assert kiosk_client.put(f"{ADMIN}/housekeeping", json=body, headers=headers).status_code == 409


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
    assert kiosk_client.get(f"{ADMIN}/policies", headers=device).status_code == 401


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
    done = kiosk_client.post(f"{ADMIN}/events/{pid}/remove", json=REMOVE, headers=headers)
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


# ---- inspection fixes (P11-001 .. P11-010) ------------------------------------------------------


def test_the_booth_stays_closed_while_guest_data_can_not_be_cleaned(
    kiosk_client: TestClient, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P11-001: a category of guests' data that can not run keeps the booth from opening."""
    from photobooth.cli import StartupCleanupError

    finished_visit(kiosk_client, container)

    def broken(_before: datetime, _dry_run: bool) -> Any:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(container.session_service, "purge_outputs", broken)
    with pytest.raises(StartupCleanupError):
        prepare_retention(container)


def test_a_file_that_will_not_go_is_counted_and_tried_again(
    kiosk_client: TestClient,
    container: Container,
    guests: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P11-010: work done before a failure is still counted; the link is gone regardless."""
    _device, sid, token = finished_visit(kiosk_client, container)
    files = container.session_service._files
    real = files.delete
    calls = {"n": 0}

    def flaky(key: str) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("held open by another program")
        real(key)

    monkeypatch.setattr(files, "delete", flaky)
    later(container, 40)
    report = container.retention_service.run(Trigger.MANUAL, dry_run=False)
    tallies = {c.value: t for c, t in report.counts.items()}
    assert tallies["originals"].failed == 1 and tallies["originals"].items == 1
    assert "originals: 1 could not be deleted" in report.errors
    assert guests.get(f"/d/{token}").status_code == 404
    again = container.retention_service.run(Trigger.MANUAL, dry_run=False)
    assert {c.value: t for c, t in again.counts.items()}["originals"].items == 1
    assert not any(stored(container, "captures", sid))
    prepare_retention(container)  # a single file is no reason to keep the booth closed


def test_a_visit_found_long_after_it_went_idle_keeps_its_real_end(
    kiosk_client: TestClient, container: Container
) -> None:
    """P11-002: a visit a restored backup brings back (or a booth that was off) ends at its
    last activity plus its timeout, so its photos are already past their time."""
    admin, device = booth(kiosk_client, container)
    activate(kiosk_client, admin, enabled_layouts=["print_3x4"])
    visit = start(kiosk_client, device)
    choose(kiosk_client, device, visit["id"], PRINT34)
    assert send(kiosk_client, device, visit["id"], 1).status_code == 200
    long_ago = datetime.now(UTC) - timedelta(days=40)
    with sqlite3.connect(container.settings.db_path) as conn:
        conn.execute(
            "UPDATE booth_sessions SET last_activity_at = ? WHERE id = ?",
            (long_ago.strftime("%Y-%m-%d %H:%M:%S.%f"), visit["id"]),
        )
    prepare_retention(container)
    ended = container.session_repository.get(visit["id"])
    assert ended is not None and ended.completed_at is not None
    assert ended.completed_at < datetime.now(UTC) - timedelta(days=39)
    assert not any(stored(container, "captures", visit["id"]))


def test_an_event_can_not_be_restored_while_it_is_being_deleted(
    kiosk_client: TestClient, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P11-003: the removal holds the event from its check to its last deletion."""
    import threading

    _device, sid, _token = finished_visit(kiosk_client, container)
    session = container.session_repository.get(sid)
    assert session is not None
    pid = session.event_profile_id
    with sqlite3.connect(container.settings.db_path) as conn:
        conn.execute(
            "UPDATE event_profiles SET is_active = 0, deleted_at = '2026-10-01 00:00:00.000000' "
            "WHERE id = ?",
            (pid,),
        )
    entered, release = threading.Event(), threading.Event()
    real = container.session_service.delete_event_visits

    def paused(profile_id: str, dry_run: bool) -> Any:
        entered.set()
        release.wait(timeout=30)
        return real(profile_id, dry_run)

    monkeypatch.setattr(container.session_service, "delete_event_visits", paused)
    removing = threading.Thread(
        target=lambda: container.retention_service.remove_event(pid, dry_run=False)
    )
    removing.start()
    assert entered.wait(timeout=30)
    outcome: list[Any] = []

    def restore() -> None:
        try:
            outcome.append(container.profile_service.restore(pid))
        except Exception as exc:
            outcome.append(exc)

    restoring = threading.Thread(target=restore)
    restoring.start()
    restoring.join(timeout=1.0)
    assert restoring.is_alive()  # it waits for the removal
    release.set()
    removing.join(timeout=60)
    restoring.join(timeout=60)
    assert container.session_repository.get(sid) is None
    assert isinstance(outcome[0], Exception)  # nothing left to restore


def test_partial_backups_ledger_and_symlinks_are_handled(
    kiosk_client: TestClient, container: Container, tmp_path: Path
) -> None:
    """P11-004, P11-005, P11-007."""
    import json

    _admin, device = booth(kiosk_client, container)
    backups = container.settings.backups_dir
    backups.mkdir(parents=True, exist_ok=True)
    month_ago = time.time() - 30 * 24 * 3600
    partial = backups / "dummy-20260901T000000Z-cccccc-0011.sqlite.partial"
    partial.write_bytes(b"half a backup")
    os.utime(partial, (month_ago, month_ago))
    old = backups / "dummy-20260901T000000Z-aaaaaa-0011.sqlite"
    old.write_bytes(b"old")
    os.utime(old, (month_ago, month_ago))
    newest = backups / "dummy-20260902T000000Z-bbbbbb-0011.sqlite"
    newest.write_bytes(b"newest")
    os.utime(newest, (month_ago + 60, month_ago + 60))
    outside = tmp_path / "elsewhere.sqlite"
    outside.write_bytes(b"not ours")
    # No symlink rights on this machine: the rest still proves the point.
    with contextlib.suppress(OSError):
        (backups / "dummy-20261231T000000Z-dddddd-0011.sqlite").symlink_to(outside)
    gone_earlier = backups / "dummy-20260801T000000Z-eeeeee-0011.sqlite"
    (backups / "BACKUPS.json").write_text(
        json.dumps(
            [
                {
                    "path": str(p),
                    "instance": "dummy",
                    "alembic_revision": "x",
                    "sha256": "0",
                    "size_bytes": 1,
                    "integrity": "ok",
                    "created_at": "2026-09-01",
                }
                for p in (gone_earlier, old, newest)
            ]
        ),
        encoding="utf-8",
    )
    done = kiosk_client.post(
        f"{ADMIN}/run", json=confirmed(container), headers=organizer(kiosk_client, device)
    )
    found = counts(done.json())
    assert found["backups"] == 1 and found["temp"] >= 1
    assert not old.exists() and not partial.exists()
    assert newest.exists() and outside.exists()
    ledger = json.loads((backups / "BACKUPS.json").read_text(encoding="utf-8"))
    assert [Path(e["path"]).name for e in ledger] == [newest.name]


def test_deleting_needs_the_settings_the_check_was_made_under(
    kiosk_client: TestClient, container: Container
) -> None:
    """P11-008: the housekeeping settings the dry run showed (visits keep their own values)."""
    _admin, device = booth(kiosk_client, container)
    headers = organizer(kiosk_client, device)
    unnamed = kiosk_client.post(f"{ADMIN}/run", json=REMOVE, headers=headers)
    assert unnamed.status_code == 422
    stale = kiosk_client.post(
        f"{ADMIN}/run", json=REMOVE | {"housekeeping_revision": 77}, headers=headers
    )
    assert stale.status_code == 409


# ---- a policy per Event Profile, frozen in each visit (P11-9) ------------------------------------


def test_each_event_keeps_its_own_policy_and_each_visit_its_own_deadlines(
    kiosk_client: TestClient, container: Container, guests: TestClient
) -> None:
    service = container.retention_service
    short = service.create_policy(
        RetentionPolicy(name="Two days", originals_days=1, outputs_days=2, link_days=1)
    )
    device, quick, token = finished_visit(kiosk_client, container, retention_policy_id=short.id)
    frozen = container.session_repository.get(quick)
    assert frozen is not None and frozen.profile.retention.policy_id == short.id
    assert frozen.profile.retention.originals_days == 1
    # The take-home link lives as long as the visit's own policy says.
    issued = container.delivery_tokens.current(quick)
    assert issued is not None
    assert issued.expires_at - issued.created_at == timedelta(days=1)

    # Later the organizer lengthens the policy: the visit keeps the deadlines it started with.
    current = service.policy(short.id)
    service.update_policy(
        short.id, replace(current, originals_days=20, outputs_days=30), current.revision
    )
    later(container, 3)
    report = service.run(Trigger.MANUAL, dry_run=False)
    tallies = {c.value: t.items for c, t in report.counts.items()}
    assert tallies["originals"] == 2 and tallies["outputs"] == 1
    assert not any(stored(container, "captures", quick))
    assert guests.get(f"/d/{token}").status_code == 404

    # A visit of an event with the Standard policy (7 / 30 days) is not due yet.
    headers = organizer(kiosk_client, device)
    other = kiosk_client.post(
        "/api/admin/profiles", json={"name": "Gala", "title": "Hi"}, headers=headers
    )
    assert other.status_code == 201, other.text
    assert other.json()["settings"]["retention_policy_id"] == STANDARD_POLICY_ID


def test_policies_are_named_kept_while_used_and_the_default_starts_new_events(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, device = booth(kiosk_client, container)
    headers = organizer(kiosk_client, device)
    body = {
        "name": "Wedding  ",
        "originals_days": 3,
        "outputs_days": 14,
        "link_days": 7,
        "metadata_mode": "anonymize",
        "metadata_days": 60,
    }
    made = kiosk_client.post(f"{ADMIN}/policies", json=body, headers=headers)
    assert made.status_code == 201, made.text
    wedding = made.json()
    assert wedding["name"] == "Wedding" and not wedding["is_default"] and wedding["used_by"] == 0
    twice = kiosk_client.post(f"{ADMIN}/policies", json=body | {"name": "wedding"}, headers=headers)
    assert twice.status_code == 409  # names are unique, whatever their case

    profile = kiosk_client.post(
        "/api/admin/profiles",
        json={"name": "Bride", "title": "Hi", "retention_policy_id": wedding["id"]},
        headers=admin,
    )
    assert profile.status_code == 201, profile.text
    assert profile.json()["settings"]["retention_policy_id"] == wedding["id"]
    unknown = kiosk_client.post(
        "/api/admin/profiles",
        json={
            "name": "X",
            "title": "Hi",
            "retention_policy_id": "11111111-1111-4111-8111-111111111111",
        },
        headers=admin,
    )
    assert unknown.status_code == 422

    in_use = kiosk_client.delete(f"{ADMIN}/policies/{wedding['id']}", headers=headers)
    assert in_use.status_code == 409  # the event uses it
    copy = kiosk_client.post(
        f"/api/admin/profiles/{profile.json()['id']}/duplicate", json={}, headers=admin
    )
    assert copy.status_code == 201, copy.text
    assert copy.json()["settings"]["retention_policy_id"] == wedding["id"]
    listed = {p["id"]: p for p in kiosk_client.get(f"{ADMIN}/policies", headers=device).json()}
    assert listed[wedding["id"]]["used_by"] == 2

    standard_gone = kiosk_client.delete(f"{ADMIN}/policies/{STANDARD_POLICY_ID}", headers=headers)
    assert standard_gone.status_code == 409  # the default can not be deleted
    made_default = kiosk_client.post(f"{ADMIN}/policies/{wedding['id']}/default", headers=headers)
    assert made_default.status_code == 200 and made_default.json()["is_default"]
    fresh = kiosk_client.post(
        "/api/admin/profiles", json={"name": "Later", "title": "Hi"}, headers=admin
    )
    assert fresh.json()["settings"]["retention_policy_id"] == wedding["id"]
    defaults = [
        p for p in kiosk_client.get(f"{ADMIN}/policies", headers=device).json() if p["is_default"]
    ]
    assert [p["id"] for p in defaults] == [wedding["id"]]  # exactly one default

    spare = kiosk_client.post(f"{ADMIN}/policies", json=body | {"name": "Spare"}, headers=headers)
    assert (
        kiosk_client.delete(f"{ADMIN}/policies/{spare.json()['id']}", headers=headers).status_code
        == 204
    )
    assert (
        kiosk_client.delete(f"{ADMIN}/policies/{spare.json()['id']}", headers=headers).status_code
        == 404
    )


def test_an_edit_keeps_the_profiles_policy_unless_it_names_another(
    kiosk_client: TestClient, container: Container
) -> None:
    admin, _device = booth(kiosk_client, container)
    other = container.retention_service.create_policy(RetentionPolicy(name="Other"))
    created = kiosk_client.post(
        "/api/admin/profiles",
        json={"name": "Keep", "title": "Hi", "retention_policy_id": other.id},
        headers=admin,
    ).json()
    settings = {k: v for k, v in created["settings"].items() if k != "retention_policy_id"}
    edited = kiosk_client.put(
        f"/api/admin/profiles/{created['id']}",
        json=settings | {"revision": created["revision"], "title": "Hello"},
        headers=admin,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["settings"]["retention_policy_id"] == other.id
    moved = kiosk_client.put(
        f"/api/admin/profiles/{created['id']}",
        json=settings
        | {"revision": edited.json()["revision"], "retention_policy_id": STANDARD_POLICY_ID},
        headers=admin,
    )
    assert moved.json()["settings"]["retention_policy_id"] == STANDARD_POLICY_ID


def test_a_policy_can_not_be_deleted_while_a_profile_is_choosing_it(
    container: Container,
) -> None:
    """The deletion holds the profiles still from its check to the deletion itself."""
    import threading

    service = container.retention_service
    doomed = service.create_policy(RetentionPolicy(name="Doomed"))
    entered, release = threading.Event(), threading.Event()
    real = container.profile_service.profiles_using

    def paused(policy_id: str) -> int:
        entered.set()
        release.wait(timeout=30)
        return real(policy_id)

    container.profile_service.profiles_using = paused  # type: ignore[method-assign]
    deleting = threading.Thread(target=lambda: service.delete_policy(doomed.id))
    deleting.start()
    assert entered.wait(timeout=30)
    outcome: list[Any] = []

    def choose_it() -> None:
        try:
            outcome.append(
                container.profile_service.create(
                    ProfileSettings(name="Chooser", title="Hi", retention_policy_id=doomed.id)
                )
            )
        except Exception as exc:
            outcome.append(exc)

    choosing = threading.Thread(target=choose_it)
    choosing.start()
    choosing.join(timeout=1.0)
    assert choosing.is_alive()  # it waits for the deletion
    release.set()
    deleting.join(timeout=60)
    choosing.join(timeout=60)
    assert service.policies() and doomed.id not in {p.id for p in service.policies()}
    assert isinstance(outcome[0], Exception)  # the policy it named is gone: refused


def organizer(client: TestClient, device: dict[str, str]) -> dict[str, str]:
    """The device headers plus the CSRF header of the organizer signed in on this client."""
    session = client.get("/api/admin/auth/session", headers=device)
    assert session.status_code == 200, session.text
    return {**device, CSRF_HEADER: session.json()["csrf_token"]}
