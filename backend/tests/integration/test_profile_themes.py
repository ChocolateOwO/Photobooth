"""Event Profile themes and main colours: persistence, duplication, conflicts, derivation."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from photobooth.container import Container
from photobooth.core.config import AppSettings
from photobooth.core.migrations import Migrator
from photobooth.main import KioskAppOptions, create_kiosk_app
from photobooth.modules.frames.builtin import builtin_frame_id
from photobooth.modules.themes.domain import PRESETS, TOKEN_KEYS, contrast_problems
from tests.integration.admin_support import login

BASE = "/api/admin/profiles"


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Themed",
        "title": "Welcome",
        "enabled_layouts": ["strip_2x6", "print_3x4", "print_4x6"],
    }
    body.update(overrides)
    return body


def _theme(preset: str = "blush_wedding", **changes: str) -> dict[str, Any]:
    tokens = {**PRESETS[preset].tokens, **changes}
    return {"tokens": tokens, "source": "custom" if changes else "preset", "preset": preset}


def test_theme_and_builtin_frames_are_saved_and_normalized(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    theme = _theme(heading="#1a2b3c")
    created = kiosk_client.post(BASE, json=_body(theme=theme), headers=headers)
    assert created.status_code == 201, created.text
    settings = created.json()["settings"]
    assert settings["theme"]["tokens"]["heading"] == "#1A2B3C"  # stored upper case
    assert (
        settings["theme"]["source"] == "custom" and settings["theme"]["preset"] == "blush_wedding"
    )
    assert settings["enabled_layouts"] == ["print_3x4", "print_4x6", "strip_2x6"]


def test_extracted_theme_keeps_its_palette(kiosk_client: TestClient, container: Container) -> None:
    headers = login(kiosk_client, container)
    theme = {
        "tokens": PRESETS["neon_party"].tokens,
        "source": "extracted",
        "preset": None,
        "palette": ["#112233", "#ddeeff"],
    }
    created = kiosk_client.post(BASE, json=_body(theme=theme), headers=headers).json()
    assert created["settings"]["theme"]["palette"] == ["#112233", "#DDEEFF"]
    too_many = {**theme, "palette": ["#000000"] * 9}
    assert (
        kiosk_client.post(BASE, json=_body(name="x", theme=too_many), headers=headers).status_code
        == 422
    )


def test_main_colours_regenerate_the_related_colours_accessibly(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    base = PRESETS["minimal_light"].tokens
    response = kiosk_client.post(
        "/api/admin/themes/main-colours",
        json={"tokens": base, "button": "#7c3aed", "text": "#14532d"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    tokens = data["tokens"]
    assert set(tokens) == set(TOKEN_KEYS)
    assert (tokens["primary_bg"], tokens["heading"]) == ("#7C3AED", "#14532D")  # kept as chosen
    assert (data["button"], data["text"]) == ("#7C3AED", "#14532D")
    # Related shades follow the main colours...
    for key in ("primary_hover", "primary_pressed", "secondary_bg", "link", "focus_ring"):
        assert tokens[key] != base[key], key
    for key in ("body", "muted", "input_border"):
        assert tokens[key] != base[key], key
    # ...page and status colours stay, and everything still meets the contrast rules.
    for key in ("background", "surface", "input_bg", "success_bg", "error_text", "danger_bg"):
        assert tokens[key] == base[key], key
    assert contrast_problems(tokens) == []

    # An unreadable choice is adjusted (same hue) instead of being accepted as it is.
    pale = kiosk_client.post(
        "/api/admin/themes/main-colours",
        json={"tokens": base, "button": "#FFFFFF", "text": "#F8FAFC"},
        headers=headers,
    ).json()
    assert pale["text"] != "#F8FAFC" and contrast_problems(pale["tokens"]) == []
    # Admin only, and only complete themes.
    partial = kiosk_client.post(
        "/api/admin/themes/main-colours",
        json={"tokens": {"heading": "#000000"}, "button": "#000000", "text": "#000000"},
        headers=headers,
    )
    assert partial.status_code == 422
    kiosk_client.cookies.delete("pb_admin_dummy", path="/api/admin")
    assert (
        kiosk_client.post(
            "/api/admin/themes/main-colours",
            json={"tokens": base, "button": "#000000", "text": "#000000"},
            headers=headers,
        ).status_code
        == 401
    )


def test_theme_edits_use_revision_conflicts_and_duplicates_copy_the_theme(
    kiosk_client: TestClient, container: Container
) -> None:
    headers = login(kiosk_client, container)
    profile = kiosk_client.post(
        BASE, json=_body(theme=_theme("forest_fresh")), headers=headers
    ).json()
    first = kiosk_client.put(
        f"{BASE}/{profile['id']}",
        json={**_body(theme=_theme("sunset_coral")), "revision": profile["revision"]},
        headers=headers,
    )
    assert first.status_code == 200
    stale = kiosk_client.put(
        f"{BASE}/{profile['id']}",
        json={**_body(theme=_theme("neon_party")), "revision": profile["revision"]},
        headers=headers,
    )
    assert stale.status_code == 409
    current = kiosk_client.get(f"{BASE}/{profile['id']}").json()
    assert current["settings"]["theme"]["preset"] == "sunset_coral"

    copy = kiosk_client.post(f"{BASE}/{profile['id']}/duplicate", json={}, headers=headers).json()
    assert copy["settings"]["theme"] == current["settings"]["theme"]
    assert copy["settings"]["enabled_layouts"] == current["settings"]["enabled_layouts"]


def test_theme_and_frames_survive_a_restart(settings: AppSettings) -> None:
    Migrator(settings.db_path).upgrade("head")
    first = Container(settings)
    first.system_service.stamp_instance()
    first.restore_builtin_files()
    try:
        with TestClient(
            create_kiosk_app(first.registry, KioskAppOptions()), base_url="http://127.0.0.1:18111"
        ) as client:
            headers = login(client, first)
            created = client.post(
                BASE, json=_body(theme=_theme("celebration_gold")), headers=headers
            ).json()
    finally:
        first.close()

    second = Container(settings)
    second.restore_builtin_files()
    try:
        with TestClient(
            create_kiosk_app(second.registry, KioskAppOptions()), base_url="http://127.0.0.1:18111"
        ) as client:
            login(client, second, create_user=False)
            reloaded = client.get(f"{BASE}/{created['id']}").json()
            assert reloaded["settings"]["theme"] == created["settings"]["theme"]
            assert reloaded["settings"]["enabled_layouts"] == created["settings"]["enabled_layouts"]
            frame_id = builtin_frame_id("midnight", "strip_2x6")
            assert client.get(f"/api/admin/frames/{frame_id}/content").status_code == 200
    finally:
        second.close()
