"""Command-line entry point: serve, database upgrade/downgrade, backup, env and OpenAPI export."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import json
import logging
import os
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

import uvicorn
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import NullPool

from photobooth.container import Container
from photobooth.core.config import AppSettings
from photobooth.core.errors import InstanceGuardError, PhotoboothError
from photobooth.core.instance_guard import PORT_TABLE, InstanceGuard, InstanceLock, real_path
from photobooth.core.listeners import build_server, listener_specs, screen_spec, serve_together
from photobooth.core.logging import configure_logging
from photobooth.core.migrations import Migrator
from photobooth.core.screen_gate import ScreenGateMiddleware
from photobooth.core.sqlite_backup import SqliteBackupService
from photobooth.core.web import ServiceRegistry
from photobooth.main import KioskAppOptions, create_delivery_app, create_kiosk_app
from photobooth.modules.auth.domain import PasswordPolicyError
from photobooth.modules.retention.domain import Trigger
from photobooth.modules.system.repository import SqlAppMetaRepository

log = logging.getLogger("photobooth")


def _load(args: argparse.Namespace) -> tuple[AppSettings, InstanceGuard]:
    settings = AppSettings.from_env_file(
        Path(args.env_file), git_commit=os.environ.get("PHOTOBOOTH_GIT_COMMIT")
    )
    guard = InstanceGuard(settings)
    guard.check_static()
    _check_intent(settings, args)
    return settings, guard


def _check_intent(settings: AppSettings, args: argparse.Namespace) -> None:
    """Launchers state which instance they mean; refuse before any mutation if the file differs."""
    expect_root = getattr(args, "expect_root", None)
    expect_profile = getattr(args, "expect_profile", None)
    if expect_root is not None and real_path(settings.instance_root) != real_path(
        Path(expect_root)
    ):
        raise InstanceGuardError(
            "intent",
            f"env file targets {real_path(settings.instance_root)}, launcher expected "
            f"{real_path(Path(expect_root))}",
        )
    if expect_profile is not None and settings.profile != expect_profile:
        raise InstanceGuardError(
            "intent", f"env file profile '{settings.profile}', launcher expected '{expect_profile}'"
        )


def cmd_serve(args: argparse.Namespace) -> int:
    settings, guard = _load(args)
    configure_logging(settings.logs_dir)
    with InstanceLock(settings.lock_path):
        container = Container(settings)
        try:
            guard.check_database(container.app_meta)
            migrator = Migrator(settings.db_path)
            if migrator.current_revision() == migrator.head_revision():
                container.restore_builtin_files()
                # Photos left half-published by a process that died are settled before serving.
                container.session_service.recover()
                # Anything past its time (also whatever an older backup brought back after a
                # restore) is deleted before the booth opens.
                prepare_retention(container)
            kiosk_spec, delivery_spec = listener_specs(settings)
            kiosk_app = create_kiosk_app(
                container.registry,
                KioskAppOptions(
                    max_request_bytes=settings.max_request_bytes,
                    frontend_dist=settings.frontend_dist,
                ),
            )
            servers = [
                build_server(kiosk_app, kiosk_spec),
                build_server(create_delivery_app(container.registry), delivery_spec),
            ]
            tv_spec = screen_spec(settings)
            if tv_spec is not None:
                # The same kiosk app, behind the gate that keeps Admin off the LAN.
                tv_app = ScreenGateMiddleware(kiosk_app, settings.kiosk_port)
                servers.append(build_server(tv_app, tv_spec))
                log.info("TV screen listener on %s:%s", tv_spec.host, tv_spec.port)
            log.info(
                "starting instance=%s profile=%s kiosk=%s:%s delivery=%s:%s boot=%s",
                settings.instance,
                settings.profile,
                kiosk_spec.host,
                kiosk_spec.port,
                delivery_spec.host,
                delivery_spec.port,
                container.boot_id,
            )
            try:
                asyncio.run(_serve_with_upkeep(servers, container))
            except KeyboardInterrupt:
                log.info("stopped by operator")
        finally:
            container.close()
    return 0


# Categories that hold guests' data: the booth does not open while one of them can not be cleaned.
_GUEST_DATA = frozenset({"originals", "outputs", "visits_anonymized", "visits_deleted"})


class StartupCleanupError(PhotoboothError):
    def __init__(self, categories: Sequence[str]) -> None:
        super().__init__(
            "the startup cleanup could not run for "
            + ", ".join(categories)
            + "; the booth stays closed so no expired photo or visit can be reached. Check the "
            "log, fix the cause (for example a locked database) and start the booth again."
        )


def prepare_retention(container: Container) -> None:
    """Before the booth opens: visits nobody came back to are ended (with their real end time),
    then everything past its time is deleted, including whatever a restored older backup brought
    back. A category of guests' data that can not run at all keeps the booth closed (one retry);
    a single file that will not go is reported and tried again later (its link is already gone).
    """
    container.session_service.close_inactive()
    for attempt in (1, 2):
        report = container.retention_service.run(Trigger.STARTUP, dry_run=False)
        broken = sorted(c.value for c in report.broken if c.value in _GUEST_DATA)
        log.info(
            "startup cleanup: %s item(s) past their time deleted%s",
            report.total,
            f"; problems: {', '.join(report.errors)}" if report.errors else "",
        )
        if not broken:
            return
        if attempt == 2:
            raise StartupCleanupError(broken)


# How often the running booth ends idle visits, settles leftovers and deletes unwanted files.
UPKEEP_SECONDS = 60.0


async def _serve_with_upkeep(servers: list[uvicorn.Server], container: Container) -> None:
    async def upkeep() -> None:
        while True:
            await asyncio.sleep(UPKEEP_SECONDS)
            try:
                await asyncio.to_thread(container.maintain)
            except Exception:  # never take the booth down; the next round tries again
                log.exception("periodic upkeep failed")

    task = asyncio.create_task(upkeep())
    try:
        await serve_together(servers)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def read_existing_stamp(db_path: Path) -> str | None:
    """Read `app_meta.instance` without creating or migrating the database (read-only)."""
    if not db_path.is_file():
        return None
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_meta'"
        ).fetchone()
        if not has_table:
            return None
        row = conn.execute("SELECT value FROM app_meta WHERE key='instance'").fetchone()
        return None if row is None else str(row[0])
    finally:
        conn.close()


def _refuse_foreign_database(settings: AppSettings, require_stamp: bool) -> None:
    """Validate the stamp BEFORE any schema change in either direction."""
    stamp = read_existing_stamp(settings.db_path)
    if stamp is not None and stamp != settings.instance:
        raise InstanceGuardError(
            "database", f"database belongs to instance '{stamp}', not '{settings.instance}'"
        )
    if require_stamp and stamp is None:
        raise InstanceGuardError(
            "database", "refusing to downgrade a database without this instance's stamp"
        )


def cmd_db_upgrade(args: argparse.Namespace) -> int:
    settings, _guard = _load(args)
    with InstanceLock(settings.lock_path):
        # Unstamped (fresh) databases are initialized and stamped; foreign ones are never touched.
        _refuse_foreign_database(settings, require_stamp=False)
        migrator = Migrator(settings.db_path)
        migrator.upgrade(args.revision)
        container = Container(settings)
        try:
            stamped = container.system_service.stamp_instance()
            if migrator.current_revision() == migrator.head_revision():
                # Built-in frame rows exist from 0004 on; their packaged files go into storage.
                container.restore_builtin_files()
                # Photos left half-published by a process that died are settled before serving.
                container.session_service.recover()
        finally:
            container.close()
    print(json.dumps({"db": str(settings.db_path), "revision": args.revision, "instance": stamped}))
    return 0


def cmd_db_downgrade(args: argparse.Namespace) -> int:
    settings, _guard = _load(args)
    with InstanceLock(settings.lock_path):
        _refuse_foreign_database(settings, require_stamp=True)
        Migrator(settings.db_path).downgrade(args.revision)
    print(json.dumps({"db": str(settings.db_path), "revision": args.revision}))
    return 0


def _read_only_engine(db_path: Path) -> Engine:
    """SQLite opened read-only: no directory, no file, no journal-mode change is ever made."""
    uri = db_path.resolve().as_uri() + "?mode=ro"
    return create_engine(
        "sqlite://", creator=lambda: sqlite3.connect(uri, uri=True), poolclass=NullPool
    )


def cmd_db_check(args: argparse.Namespace) -> int:
    """Read only (P13-R6): a missing database is refused, never created, and nothing is written;
    exit 0 at the code's head, 3 behind it, 4 without a database."""
    settings, guard = _load(args)
    head = Migrator(settings.db_path).head_revision()
    if not settings.db_path.is_file():
        print(
            json.dumps(
                {"current": None, "head": head, "instance": settings.instance, "database": "none"}
            )
        )
        return 4
    engine = _read_only_engine(settings.db_path)
    try:
        meta = SqlAppMetaRepository(engine)
        guard.check_database(meta)
        current = meta.schema_revision()
    finally:
        engine.dispose()
    print(json.dumps({"current": current, "head": head, "instance": settings.instance}))
    return 0 if current == head else 3


def cmd_backup(args: argparse.Namespace) -> int:
    settings, _guard = _load(args)
    record = SqliteBackupService(settings.backups_dir).create_backup(
        settings.db_path, settings.instance
    )
    print(json.dumps(record.__dict__, ensure_ascii=False))
    return 0


def cmd_init_env(args: argparse.Namespace) -> int:
    """Write a UTF-8 env file (avoids PowerShell 5.1 encoding pitfalls with Thai paths)."""
    output = Path(args.output)
    if output.exists() and not args.force:
        print(f"refusing to overwrite existing env file: {output}", file=sys.stderr)
        return 2
    ports = PORT_TABLE.get((args.instance, args.profile))
    kiosk_port = args.kiosk_port or (ports.kiosk if ports else None)
    delivery_port = args.delivery_port or (ports.delivery if ports else None)
    if kiosk_port is None or delivery_port is None:
        print("ports required for this profile", file=sys.stderr)
        return 2
    lines = [
        f"PHOTOBOOTH_INSTANCE={args.instance}",
        f"PHOTOBOOTH_PROFILE={args.profile}",
        f"PHOTOBOOTH_INSTANCE_ROOT={Path(args.instance_root).resolve()}",
        "PHOTOBOOTH_KIOSK_HOST=127.0.0.1",
        f"PHOTOBOOTH_KIOSK_PORT={kiosk_port}",
        f"PHOTOBOOTH_DELIVERY_HOST={args.delivery_host}",
        f"PHOTOBOOTH_DELIVERY_PORT={delivery_port}",
    ]
    ui_port = args.ui_port or (ports.ui if ports else None)
    if ui_port is not None:
        lines.append(f"PHOTOBOOTH_UI_PORT={ui_port}")
    if args.frontend_dist:
        lines.append(f"PHOTOBOOTH_FRONTEND_DIST={Path(args.frontend_dist).resolve()}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(str(output))
    return 0


def _read_new_password(args: argparse.Namespace) -> str:
    if args.password_stdin:
        # Windows PowerShell pipes text with a UTF-8 BOM; it is never part of the password.
        return sys.stdin.readline().rstrip("\r\n").removeprefix("﻿")
    first = getpass.getpass("New admin password: ")
    if getpass.getpass("Repeat password: ") != first:
        raise PasswordPolicyError("passwords do not match")
    return first


def cmd_admin_set_password(args: argparse.Namespace) -> int:
    """Create the admin user or replace its password (Argon2id). The booth must be stopped, so
    no running process keeps sessions made with the old password."""
    settings, guard = _load(args)
    with InstanceLock(settings.lock_path):
        migrator = Migrator(settings.db_path)
        if migrator.current_revision() != migrator.head_revision():
            raise InstanceGuardError("database", "database is not at head; run 'db-upgrade' first")
        container = Container(settings)
        try:
            guard.check_database(container.app_meta)
            try:
                user = container.auth_service.set_password(args.username, _read_new_password(args))
            except PasswordPolicyError as exc:
                print(f"photobooth: {exc}", file=sys.stderr)
                return 2
        finally:
            container.close()
    print(json.dumps({"username": user.username, "instance": settings.instance}))
    return 0


def cmd_export_openapi(args: argparse.Namespace) -> int:
    app = create_kiosk_app(ServiceRegistry(), KioskAppOptions())
    text = json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    Path(args.output).write_text(text, encoding="utf-8")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="photobooth")
    sub = parser.add_subparsers(dest="command", required=True)

    def with_env(name: str, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--env-file", required=True)
        p.add_argument("--expect-root", help="refuse unless the env file targets this root")
        p.add_argument(
            "--expect-profile", choices=["dev", "e2e", "test", "prod"], help="refuse on mismatch"
        )
        return p

    with_env("serve", "run kiosk + delivery listeners").set_defaults(func=cmd_serve)
    up = with_env("db-upgrade", "apply migrations and stamp the instance")
    up.add_argument("--revision", default="head")
    up.set_defaults(func=cmd_db_upgrade)
    down = with_env("db-downgrade", "downgrade schema (take a backup first)")
    down.add_argument("--revision", required=True)
    down.set_defaults(func=cmd_db_downgrade)
    with_env("db-check", "verify instance stamp and head revision").set_defaults(func=cmd_db_check)
    with_env("backup", "online backup + verification").set_defaults(func=cmd_backup)
    pw = with_env("admin-set-password", "create the admin user or change its password")
    pw.add_argument("--username", default="admin")
    pw.add_argument(
        "--password-stdin", action="store_true", help="read the password from the first stdin line"
    )
    pw.set_defaults(func=cmd_admin_set_password)

    init = sub.add_parser("init-env", help="write an instance env file")
    init.add_argument("--instance", required=True, choices=["dummy", "main"])
    init.add_argument("--profile", required=True, choices=["dev", "e2e", "test", "prod"])
    init.add_argument("--instance-root", required=True)
    init.add_argument("--output", required=True)
    init.add_argument("--kiosk-port", type=int)
    init.add_argument("--delivery-port", type=int)
    init.add_argument("--ui-port", type=int)
    init.add_argument("--delivery-host", default="0.0.0.0")  # noqa: S104 - LAN delivery listener
    init.add_argument("--frontend-dist")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init_env)

    oa = sub.add_parser("export-openapi", help="write the kiosk OpenAPI document")
    oa.add_argument("--output", required=True)
    oa.set_defaults(func=cmd_export_openapi)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except PhotoboothError as exc:
        print(f"photobooth: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
