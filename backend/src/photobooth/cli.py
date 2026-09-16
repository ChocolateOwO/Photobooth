"""Command-line entry point: serve, database upgrade/downgrade, backup, env and OpenAPI export."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from photobooth.container import Container
from photobooth.core.config import AppSettings
from photobooth.core.db import create_sqlite_engine
from photobooth.core.errors import PhotoboothError
from photobooth.core.instance_guard import PORT_TABLE, InstanceGuard, InstanceLock
from photobooth.core.listeners import build_server, listener_specs, serve_together
from photobooth.core.logging import configure_logging
from photobooth.core.migrations import Migrator
from photobooth.core.sqlite_backup import SqliteBackupService
from photobooth.core.web import ServiceRegistry
from photobooth.main import KioskAppOptions, create_delivery_app, create_kiosk_app
from photobooth.modules.system.repository import SqlAppMetaRepository

log = logging.getLogger("photobooth")


def _load(env_file: str) -> tuple[AppSettings, InstanceGuard]:
    settings = AppSettings.from_env_file(Path(env_file))
    guard = InstanceGuard(settings)
    guard.check_static()
    return settings, guard


def cmd_serve(args: argparse.Namespace) -> int:
    settings, guard = _load(args.env_file)
    configure_logging(settings.logs_dir)
    with InstanceLock(settings.lock_path):
        container = Container(settings)
        try:
            guard.check_database(container.app_meta)
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
                build_server(create_delivery_app(), delivery_spec),
            ]
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
                asyncio.run(serve_together(servers))
            except KeyboardInterrupt:
                log.info("stopped by operator")
        finally:
            container.close()
    return 0


def cmd_db_upgrade(args: argparse.Namespace) -> int:
    settings, _guard = _load(args.env_file)
    with InstanceLock(settings.lock_path):
        Migrator(settings.db_path).upgrade(args.revision)
        container = Container(settings)
        try:
            stamped = container.system_service.stamp_instance()
        finally:
            container.close()
    print(json.dumps({"db": str(settings.db_path), "revision": args.revision, "instance": stamped}))
    return 0


def cmd_db_downgrade(args: argparse.Namespace) -> int:
    settings, _guard = _load(args.env_file)
    with InstanceLock(settings.lock_path):
        Migrator(settings.db_path).downgrade(args.revision)
    print(json.dumps({"db": str(settings.db_path), "revision": args.revision}))
    return 0


def cmd_db_check(args: argparse.Namespace) -> int:
    settings, guard = _load(args.env_file)
    engine = create_sqlite_engine(settings.db_path)
    try:
        guard.check_database(SqlAppMetaRepository(engine))
    finally:
        engine.dispose()
    migrator = Migrator(settings.db_path)
    current, head = migrator.current_revision(), migrator.head_revision()
    print(json.dumps({"current": current, "head": head, "instance": settings.instance}))
    return 0 if current == head else 3


def cmd_backup(args: argparse.Namespace) -> int:
    settings, _guard = _load(args.env_file)
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
    if args.frontend_dist:
        lines.append(f"PHOTOBOOTH_FRONTEND_DIST={Path(args.frontend_dist).resolve()}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(str(output))
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

    init = sub.add_parser("init-env", help="write an instance env file")
    init.add_argument("--instance", required=True, choices=["dummy", "main"])
    init.add_argument("--profile", required=True, choices=["dev", "e2e", "test", "prod"])
    init.add_argument("--instance-root", required=True)
    init.add_argument("--output", required=True)
    init.add_argument("--kiosk-port", type=int)
    init.add_argument("--delivery-port", type=int)
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
