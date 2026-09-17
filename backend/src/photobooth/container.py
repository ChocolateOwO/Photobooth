"""Composition root: the only place that wires concrete infrastructure to services."""

from __future__ import annotations

import secrets
import time

from photobooth import API_VERSION, __version__
from photobooth.core.config import AppSettings
from photobooth.core.db import create_sqlite_engine
from photobooth.core.kiosk_pairing import (
    LAUNCHER_TOKEN_FILENAME,
    Clock,
    DeviceCredentialRegistry,
    FilePairingCodeStore,
    LauncherCredential,
    PairingService,
    RuntimeSecretFile,
)
from photobooth.core.web import DeviceCookieSettings, ServiceRegistry
from photobooth.modules.kiosk.service import KioskPairingService
from photobooth.modules.rendering.queue import RenderQueue
from photobooth.modules.rendering.renderer import PillowPhotoRenderer, PillowSampleImageFactory
from photobooth.modules.rendering.service import RenderService
from photobooth.modules.system.domain import AppMetaRepository
from photobooth.modules.system.repository import SqlAppMetaRepository
from photobooth.modules.system.service import SystemIdentity, SystemService
from photobooth.modules.templates.imaging import PillowTemplateArtist
from photobooth.modules.templates.repository import JsonTemplateRepository
from photobooth.modules.templates.service import TemplateSpecService


class Container:
    """Owns process-lifetime resources for one instance."""

    def __init__(self, settings: AppSettings, clock: Clock = time.monotonic) -> None:
        self.settings = settings
        self.boot_id = secrets.token_hex(8)
        self.engine = create_sqlite_engine(settings.db_path)

        self.app_meta: AppMetaRepository = SqlAppMetaRepository(self.engine)
        self.system_service = SystemService(
            self.app_meta,
            SystemIdentity(
                instance=settings.instance,
                app_version=__version__,
                api_version=API_VERSION,
                git_commit=settings.git_commit,
            ),
        )

        self.device_credentials = DeviceCredentialRegistry()
        self.pairing_store = FilePairingCodeStore(settings.runtime_dir)
        self.pairing_store.clear()  # a code from a previous process is never valid
        self.pairing = PairingService(self.pairing_store, self.device_credentials, clock=clock)
        self.kiosk_pairing_service = KioskPairingService(self.pairing)
        self.launcher = LauncherCredential(
            RuntimeSecretFile(settings.runtime_dir, LAUNCHER_TOKEN_FILENAME)
        )

        self.template_service = TemplateSpecService(
            JsonTemplateRepository(), PillowTemplateArtist()
        )
        self.render_queue = RenderQueue(max_pending=4)
        self.render_service = RenderService(
            PillowPhotoRenderer(),
            self.template_service,
            PillowSampleImageFactory(),
            self.render_queue,
        )

        self.registry = ServiceRegistry()
        self.registry.register(SystemService, self.system_service)
        self.registry.register(KioskPairingService, self.kiosk_pairing_service)
        self.registry.register(TemplateSpecService, self.template_service)
        self.registry.register(RenderService, self.render_service)
        self.registry.register(DeviceCredentialRegistry, self.device_credentials)
        self.registry.register(LauncherCredential, self.launcher)
        self.registry.register(
            DeviceCookieSettings,
            DeviceCookieSettings(settings.device_cookie_name, settings.allowed_origins),
        )

    def close(self) -> None:
        self.pairing.shutdown()
        self.launcher.clear()
        self.render_queue.shutdown()
        self.engine.dispose()
