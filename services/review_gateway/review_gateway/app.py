"""One gateway instance: its store, the two ASGI applications that share it and the Immich uploader."""

from __future__ import annotations

from starlette.applications import Starlette

from .config import Settings, read_secret, running_release
from .contract import Contract
from .deploy_inbox import DeployInbox
from .media import MediaStore
from .phone_app import build_phone_app
from .rating_store import RatingStore
from .store import Clock, Store, utc_now
from .sync_app import build_sync_app
from .timing_store import TimingStore
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
            undecided_days=settings.undecided_days,
            cache_warn_bytes=settings.cache_warn_gib * 1024**3,
        )
        self.ratings = RatingStore(self.store)
        self.timings = TimingStore(settings.data_dir / "timing.sqlite3", clock)

    def phone_app(self) -> Starlette:
        release = self.settings.release_dir or running_release()
        return build_phone_app(self.store, self.clock, self.ratings, self.timings, release)

    def sync_app(self) -> Starlette:
        deploys = DeployInbox(
            self.settings.deploy_switch_file,
            self.settings.deploy_dir,
            self.settings.release_dir or running_release(),
        )
        return build_sync_app(
            self.store,
            self.contract,
            read_secret(self.settings.secret_file),
            deploys,
            self.ratings,
            self.timings,
        )

    def uploader(self) -> Uploader:
        return Uploader(self.store, self.settings.immich_url, self.settings.immich_key_path)

    def retention(self) -> dict[str, int]:
        return {**self.store.retention(), **self.ratings.retention(), **self.timings.retention()}
