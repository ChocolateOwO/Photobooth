"""Event Profiles: CRUD, duplicate, atomic activation, soft delete/restore, persistence."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from photobooth.container import Container
from photobooth.core.config import AppSettings
from photobooth.core.migrations import Migrator
from photobooth.main import KioskAppOptions, create_kiosk_app
from photobooth.modules.event_profiles.domain import ProfileConflictError, ProfileSettings
from photobooth.modules.themes.domain import DEFAULT_PRESET, PRESETS
from tests.integration.admin_support import jpeg, login, png

BASE = "/api/admin/profiles"


def body(name: str = "Wedding", **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "name": name,
        "title": "Welcome to the booth",
        "subtitle": "Tap start when you are ready",
        "start_button_text": "Start",
        "enabled_layouts": ["strip_2x6", "print_4x6"],
        "countdown_seconds": 5,
        "mirror": True,
        "inactivity_timeout_s": 90,
        "retake_mode": "per_photo",
        "delivery_mode": "local_link",
    }
    values.update(overrides)
    return values


@pytest.fixture
def admin(kiosk_client: TestClient, container: Container) -> dict[str, str]:
    return login(kiosk_client, container)


def _create(client: TestClient, headers: dict[str, str], **kwargs: Any) -> dict[str, Any]:
    response = client.post(BASE, json=body(**kwargs), headers=headers)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def _asset(client: TestClient, headers: dict[str, str], kind: str, data: bytes) -> str:
    response = client.post(
        "/api/admin/assets", data={"kind": kind}, files={"file": ("f", data)}, headers=headers
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_create_get_list_update(kiosk_client: TestClient, admin: dict[str, str]) -> None:
    logo = _asset(kiosk_client, admin, "logo", png())
    background = _asset(kiosk_client, admin, "background", jpeg())
    created = _create(
        kiosk_client, admin, logo_asset_id=logo, background_asset_id=background, mirror=False
    )
    settings = created["settings"]
    assert created["revision"] == 1 and created["is_active"] is False
    assert created["deleted_at"] is None
    # No theme sent: the default preset, complete.
    assert settings["theme"]["preset"] == DEFAULT_PRESET
    assert settings["theme"]["tokens"] == PRESETS[DEFAULT_PRESET].tokens
    assert settings["enabled_layouts"] == ["strip_2x6", "print_4x6"]  # order kept
    assert settings["logo_asset_id"] == logo and settings["background_asset_id"] == background
    assert settings["mirror"] is False and settings["countdown_seconds"] == 5

    assert kiosk_client.get(f"{BASE}/{created['id']}").json() == created
    assert [p["id"] for p in kiosk_client.get(BASE).json()] == [created["id"]]

    changed = body(title="New title", enabled_layouts=["print_3x4"], retake_mode="all")
    updated = kiosk_client.put(
        f"{BASE}/{created['id']}", json={**changed, "revision": 1}, headers=admin
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == 2
    assert updated.json()["settings"]["title"] == "New title"
    assert updated.json()["settings"]["enabled_layouts"] == ["print_3x4"]
    assert updated.json()["settings"]["logo_asset_id"] is None


def test_stale_revision_is_rejected(kiosk_client: TestClient, admin: dict[str, str]) -> None:
    created = _create(kiosk_client, admin)
    url = f"{BASE}/{created['id']}"
    assert (
        kiosk_client.put(url, json={**body(title="A"), "revision": 1}, headers=admin).status_code
        == 200
    )
    stale = kiosk_client.put(url, json={**body(title="B"), "revision": 1}, headers=admin)
    assert stale.status_code == 409
    assert kiosk_client.get(url).json()["settings"]["title"] == "A"


@pytest.mark.parametrize(
    "overrides",
    [
        {"countdown_seconds": 3},
        {"enabled_layouts": []},
        {"enabled_layouts": ["unknown_layout"]},
        {"enabled_layouts": ["strip_2x6", "strip_2x6"]},
        {"enabled_layouts": ["../strip"]},
        {"inactivity_timeout_s": 5},
        {"inactivity_timeout_s": 5000},
        {"theme": {"tokens": {**PRESETS[DEFAULT_PRESET].tokens, "heading": "red"}}},
        {"theme": {"tokens": {**PRESETS[DEFAULT_PRESET].tokens, "heading": "#12345"}}},
        {"theme": {"tokens": {"heading": "#FFFFFF"}}},
        {"theme": {"tokens": PRESETS[DEFAULT_PRESET].tokens, "preset": "no_such_preset"}},
        {"theme": {"tokens": PRESETS[DEFAULT_PRESET].tokens, "source": "magic"}},
        {"theme": {"tokens": {**PRESETS[DEFAULT_PRESET].tokens, "sparkle": "#FFFFFF"}}},
        {"retake_mode": "sometimes"},
        {"delivery_mode": "email"},
        {"name": ""},
        {"name": "   "},
        {"title": "x" * 121},
        {"title": "bad\u0000title"},
        {"logo_asset_id": "00000000-0000-4000-8000-000000000000"},
        {"logo_asset_id": "../../photobooth.sqlite"},
        {"logo_path": "C:/Windows/logo.png"},
    ],
)
def test_invalid_settings_are_rejected(
    kiosk_client: TestClient, admin: dict[str, str], overrides: dict[str, Any]
) -> None:
    response = kiosk_client.post(BASE, json=body(**overrides), headers=admin)
    assert response.status_code == 422, (overrides, response.text)
    assert kiosk_client.get(BASE).json() == []


def test_asset_kind_must_match_field(kiosk_client: TestClient, admin: dict[str, str]) -> None:
    background = _asset(kiosk_client, admin, "background", jpeg())
    response = kiosk_client.post(BASE, json=body(logo_asset_id=background), headers=admin)
    assert response.status_code == 422


def test_names_are_unique_case_insensitively_among_live_profiles(
    kiosk_client: TestClient, admin: dict[str, str]
) -> None:
    first = _create(kiosk_client, admin, name="Wedding")
    assert kiosk_client.post(BASE, json=body(name="  wedding "), headers=admin).status_code == 409
    deleted = kiosk_client.delete(f"{BASE}/{first['id']}?revision=1", headers=admin)
    assert deleted.status_code == 200
    second = _create(kiosk_client, admin, name="WEDDING")  # name is free after soft delete
    restore = kiosk_client.post(f"{BASE}/{first['id']}/restore", headers=admin)
    assert restore.status_code == 409  # restoring would duplicate a live name
    assert second["settings"]["name"] == "WEDDING"


def test_duplicate_creates_inactive_copy_with_free_name(
    kiosk_client: TestClient, admin: dict[str, str]
) -> None:
    logo = _asset(kiosk_client, admin, "logo", png())
    source = _create(kiosk_client, admin, logo_asset_id=logo)
    kiosk_client.post(f"{BASE}/{source['id']}/activate", headers=admin)

    copy1 = kiosk_client.post(f"{BASE}/{source['id']}/duplicate", headers=admin)
    copy2 = kiosk_client.post(f"{BASE}/{source['id']}/duplicate", headers=admin)
    named = kiosk_client.post(
        f"{BASE}/{source['id']}/duplicate", json={"name": "Gala"}, headers=admin
    )
    assert copy1.status_code == copy2.status_code == named.status_code == 201
    assert copy1.json()["settings"]["name"] == "Wedding (copy)"
    assert copy2.json()["settings"]["name"] == "Wedding (copy 2)"
    assert named.json()["settings"]["name"] == "Gala"
    for copy in (copy1.json(), copy2.json(), named.json()):
        assert copy["id"] != source["id"] and copy["is_active"] is False
        assert copy["revision"] == 1
        expected = {**source["settings"], "name": copy["settings"]["name"]}
        assert copy["settings"] == expected
    clash = kiosk_client.post(
        f"{BASE}/{source['id']}/duplicate", json={"name": "wedding"}, headers=admin
    )
    assert clash.status_code == 409


def test_activation_is_exclusive(kiosk_client: TestClient, admin: dict[str, str]) -> None:
    a = _create(kiosk_client, admin, name="A")
    b = _create(kiosk_client, admin, name="B")
    assert kiosk_client.post(f"{BASE}/{a['id']}/activate", headers=admin).json()["is_active"]
    assert kiosk_client.post(f"{BASE}/{b['id']}/activate", headers=admin).json()["is_active"]
    assert kiosk_client.post(f"{BASE}/{b['id']}/activate", headers=admin).status_code == 200
    states = {p["settings"]["name"]: p["is_active"] for p in kiosk_client.get(BASE).json()}
    assert states == {"A": False, "B": True}


def test_concurrent_activation_leaves_exactly_one_active(
    container: Container, kiosk_client: TestClient, admin: dict[str, str]
) -> None:
    ids = [_create(kiosk_client, admin, name=f"P{i}")["id"] for i in range(6)]
    service = container.profile_service
    errors: list[BaseException] = []
    barrier = threading.Barrier(len(ids) * 3)

    def worker(profile_id: str) -> None:
        barrier.wait()
        try:
            service.activate(profile_id)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(pid,)) for pid in ids * 3]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors
    active = [p for p in service.list_profiles() if p.is_active]
    assert len(active) == 1
    with container.engine.connect() as conn:
        assert (
            conn.execute(text("SELECT COUNT(*) FROM event_profiles WHERE is_active = 1")).scalar()
            == 1
        )


def test_database_refuses_a_second_active_row(container: Container) -> None:
    service = container.profile_service
    a = service.create(ProfileSettings(name="A", title="t"))
    b = service.create(ProfileSettings(name="B", title="t"))
    service.activate(a.id)
    with pytest.raises(IntegrityError), container.engine.begin() as conn:
        conn.execute(text("UPDATE event_profiles SET is_active = 1 WHERE id = :id"), {"id": b.id})


def test_soft_delete_and_restore(kiosk_client: TestClient, admin: dict[str, str]) -> None:
    active = _create(kiosk_client, admin, name="Active")
    other = _create(kiosk_client, admin, name="Other")
    kiosk_client.post(f"{BASE}/{active['id']}/activate", headers=admin)

    refused = kiosk_client.delete(f"{BASE}/{active['id']}?revision=1", headers=admin)
    assert refused.status_code == 409  # the active profile can not be deleted
    assert kiosk_client.delete(f"{BASE}/{other['id']}", headers=admin).status_code == 422
    assert kiosk_client.delete(f"{BASE}/{other['id']}?revision=9", headers=admin).status_code == 409

    deleted = kiosk_client.delete(f"{BASE}/{other['id']}?revision=1", headers=admin)
    assert deleted.status_code == 200
    assert deleted.json()["deleted_at"] is not None and deleted.json()["revision"] == 2
    assert [p["id"] for p in kiosk_client.get(BASE).json()] == [active["id"]]
    listed = kiosk_client.get(f"{BASE}?include_deleted=true").json()
    assert {p["id"] for p in listed} == {active["id"], other["id"]}
    assert kiosk_client.get(f"{BASE}/{other['id']}").status_code == 200  # row is kept

    url = f"{BASE}/{other['id']}"
    assert kiosk_client.post(f"{url}/activate", headers=admin).status_code == 409
    assert (
        kiosk_client.put(url, json={**body(name="Other"), "revision": 2}, headers=admin).status_code
        == 409
    )
    assert kiosk_client.post(f"{url}/duplicate", headers=admin).status_code == 409
    assert kiosk_client.delete(f"{url}?revision=2", headers=admin).status_code == 409

    restored = kiosk_client.post(f"{url}/restore", headers=admin)
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None and restored.json()["is_active"] is False
    assert kiosk_client.post(f"{url}/restore", headers=admin).status_code == 409


def test_unknown_and_malformed_ids(kiosk_client: TestClient, admin: dict[str, str]) -> None:
    missing = "00000000-0000-4000-8000-000000000000"
    assert kiosk_client.get(f"{BASE}/{missing}").status_code == 404
    assert kiosk_client.post(f"{BASE}/{missing}/activate", headers=admin).status_code == 404
    assert kiosk_client.post(f"{BASE}/{missing}/duplicate", headers=admin).status_code == 404
    assert kiosk_client.post(f"{BASE}/{missing}/restore", headers=admin).status_code == 404
    assert kiosk_client.delete(f"{BASE}/{missing}?revision=1", headers=admin).status_code == 404
    put = kiosk_client.put(f"{BASE}/{missing}", json={**body(), "revision": 1}, headers=admin)
    assert put.status_code == 404
    assert kiosk_client.get(f"{BASE}/not-a-uuid").status_code == 422


def test_unauthorized_access_is_refused(
    kiosk_client: TestClient, container: Container, admin: dict[str, str]
) -> None:
    created = _create(kiosk_client, admin)
    url = f"{BASE}/{created['id']}"
    kiosk_client.cookies.delete("pb_admin_dummy", path="/api/admin")
    for method, path, payload in (
        ("GET", BASE, None),
        ("POST", BASE, body(name="X")),
        ("GET", url, None),
        ("PUT", url, {**body(), "revision": 1}),
        ("POST", f"{url}/duplicate", None),
        ("POST", f"{url}/activate", None),
        ("DELETE", f"{url}?revision=1", None),
        ("POST", f"{url}/restore", None),
    ):
        response = kiosk_client.request(method, path, json=payload, headers=admin)
        assert response.status_code == 401, (method, path)
    assert not container.profile_service.get(created["id"]).is_active


def test_profiles_and_assets_persist_across_restart(settings: AppSettings) -> None:
    Migrator(settings.db_path).upgrade("head")
    first = Container(settings)
    first.system_service.stamp_instance()
    try:
        app = create_kiosk_app(first.registry, KioskAppOptions())
        with TestClient(app, base_url="http://127.0.0.1:18111") as client:
            headers = login(client, first)
            logo = _asset(client, headers, "logo", png())
            profile = _create(client, headers, logo_asset_id=logo)
            client.post(f"{BASE}/{profile['id']}/activate", headers=headers)
            deleted = _create(client, headers, name="Deleted")
            client.delete(f"{BASE}/{deleted['id']}?revision=1", headers=headers)
    finally:
        first.close()

    second = Container(settings)
    try:
        app = create_kiosk_app(second.registry, KioskAppOptions())
        with TestClient(app, base_url="http://127.0.0.1:18111") as client:
            login(client, second, create_user=False)
            reloaded = client.get(f"{BASE}/{profile['id']}").json()
            assert reloaded["is_active"] is True
            assert reloaded["settings"] == profile["settings"]
            assert reloaded["created_at"] == profile["created_at"]
            assert client.get(f"{BASE}/{deleted['id']}").json()["deleted_at"] is not None
            content = client.get(f"/api/admin/assets/{logo}/content")
            assert content.status_code == 200 and content.content == png()
    finally:
        second.close()


def test_service_rejects_duplicate_name_without_api(container: Container) -> None:
    service = container.profile_service
    service.create(ProfileSettings(name="Gala", title="t"))
    with pytest.raises(ProfileConflictError):
        service.create(ProfileSettings(name="GALA", title="t"))


def test_duplicate_keeps_the_copy_suffix_for_maximum_length_names(
    kiosk_client: TestClient, admin: dict[str, str]
) -> None:
    long_name = "ง" * 79 + "x"
    source = _create(kiosk_client, admin, name=long_name)
    names = []
    for _ in range(3):
        response = kiosk_client.post(f"{BASE}/{source['id']}/duplicate", headers=admin)
        assert response.status_code == 201, response.text
        names.append(response.json()["settings"]["name"])
    assert names[0].endswith(" (copy)") and names[1].endswith(" (copy 2)")
    assert names[2].endswith(" (copy 3)")
    assert all(len(n) <= 80 for n in names) and len(set(names)) == 3
