"""One gateway instance: its store, the two ASGI applications that share it and the Immich uploader."""

from __future__ import annotations

from starlette.applications import Starlette

from .config import Settings, read_secret
from .contract import Contract
from .media import MediaStore
from .phone_app import build_phone_app
from .store import Clock, Store, utc_now
from .sync_app import build_sync_app
from .uploader import Uploader


class Gateway:
    def __init__(self, settings: Settings, *, clock: Clock = utc_now) -> None:
        self.settings = settings
        self.clock = clock
        self.contract = Contract(settings.schema_file)
        self.store = Store(
            settings.data_dir / "gateway.sqlite3",
            MediaStore(settings.media_dir),
            self.contract,
            clock,
        )

    def phone_app(self) -> Starlette:
        return build_phone_app(self.store, self.clock)

    def sync_app(self) -> Starlette:
        return build_sync_app(self.store, self.contract, read_secret(self.settings.secret_file))

    def uploader(self) -> Uploader:
        return Uploader(self.store, self.settings.immich_url, self.settings.immich_key_path)

    def retention(self) -> dict[str, int]:
        return self.store.retention()
