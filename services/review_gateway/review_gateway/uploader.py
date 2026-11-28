"""The worker that pays what the upload queue owes, one item at a time, beside review.

No database transaction is held while talking to Immich, so a slow or absent Immich never blocks a decision.
Every step is safe to repeat: Immich is asked for the bytes before they are sent.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import traceback
from pathlib import Path

from . import upload_queue
from .immich import (
    MINIMUM_MAJOR,
    ImmichClient,
    ImmichError,
    ImmichRefusedGateway,
    ImmichUnavailable,
    read_key,
)
from .store import Store, stamp
from .upload_queue import Claim

_IDLE_S = 5.0
_PAUSE_FIRST_S = 30.0
_PAUSE_LIMIT_S = 900.0
_CRASH_S = 60.0
_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "video/mp4": "mp4",
    "video/webm": "webm",
}
_LOG = logging.getLogger("review_gateway")


class Uploader:
    def __init__(self, store: Store, url: str, key_file: Path) -> None:
        self.store = store
        self.url = url
        self.key_file = key_file
        self.stop = threading.Event()
        self._complaint = ""

    def client(self) -> ImmichClient | None:
        """``None`` until both the address and the key are there. The key is read again each time."""

        if not self.url:
            return None
        try:
            key = read_key(self.key_file)
        except (OSError, ValueError) as error:
            # Neither message holds the file's content.
            self._say(f"Immich key not usable: {error}")
            return None
        return None if key is None else ImmichClient(self.url, key, self.stop.is_set)

    def run_once(self) -> str:
        """Handle at most one owed upload.

        Returns ``done``, ``idle``, ``unconfigured``, ``failed`` (that item) or ``unavailable`` (Immich).
        """

        client = self.client()
        if client is None:
            return "unconfigured"
        with self.store.connection() as db:
            claimed = upload_queue.claim(db, stamp(self.store.clock()))
        if claimed is None:
            return "idle"
        try:
            self._pay(client, claimed)
        except ImmichUnavailable as error:
            self._say(f"Immich is not available ({error.code}); uploads wait")
            with self.store.write() as db:
                upload_queue.send_to_back(db, claimed, stamp(self.store.clock()))
            return "unavailable"
        except ImmichRefusedGateway as error:
            # A key or setting to fix: report it, but keep the item due for when it is fixed.
            self._say(f"Immich refused the gateway ({error.code}); uploads wait")
            with self.store.write() as db:
                upload_queue.send_to_back(db, claimed, stamp(self.store.clock()))
                upload_queue.report_failure(
                    db, self.store.contract, claimed, error.code, stamp(self.store.clock())
                )
            return "unavailable"
        except ImmichError as error:
            self._fail(claimed, error.code, transient=error.transient)
            return "failed"
        except Exception as error:  # one broken item must not stop the others
            # Frames only: an exception message could quote a request header.
            _LOG.error(
                "Immich upload stopped by %s\n%s",
                type(error).__name__,
                "".join(traceback.format_tb(error.__traceback__)),
            )
            self._fail(claimed, "internal_error", transient=True)
            return "failed"
        self._complaint = ""
        return "done"

    def _pay(self, client: ImmichClient, claimed: Claim) -> None:
        major = client.version()[0]
        if major < MINIMUM_MAJOR:
            raise ImmichRefusedGateway("immich_unsupported_version")
        asset_id = self._asset(client, claimed, major)
        self._file_in_album(client, claimed, asset_id)
        # Only ever clear a favorite the gateway set: the owner may have marked it in Immich.
        with self.store.connection() as db:
            row = db.execute(
                "SELECT favorite_set FROM immich_upload WHERE library_id = ? AND sha256 = ?",
                claimed.key,
            ).fetchone()
        if claimed.favorite:
            # Noted first: if the reply is lost, taking the favorite back must still clear it.
            with self.store.write() as db:
                upload_queue.remember_favorite(db, claimed, True)
            client.set_favorite(asset_id, True)
        elif row["favorite_set"]:
            client.set_favorite(asset_id, False)
            with self.store.write() as db:
                upload_queue.remember_favorite(db, claimed, False)
        with self.store.write() as db:
            upload_queue.succeed(db, self.store.contract, claimed, stamp(self.store.clock()))

    def _asset(self, client: ImmichClient, claimed: Claim, major: int) -> str:
        path = self.store.media.path(claimed.digest)
        if self.store.media.size(claimed.digest) is None:
            raise ImmichError("media_missing")
        with path.open("rb") as stream:
            sha1 = hashlib.file_digest(stream, "sha1").hexdigest()
        found = client.existing_asset(sha1)
        if found is None:
            asset_id, created = client.upload(
                path,
                # NAME-INFO: the schema's pattern admits only a plain, descriptive file name.
                filename=claimed.file_name
                or f"{claimed.run_id}_{claimed.sha256[:8]}.{_EXTENSIONS[claimed.content_type]}",
                content_type=claimed.content_type,
                sha1=sha1,
                created_at=claimed.created_at,
                major=major,
            )
        else:
            asset_id, trashed = found
            created = False
            if trashed:
                # Immich will delete it for good later; that is not a kept copy.
                raise ImmichError("immich_asset_trashed")
        with self.store.write() as db:
            upload_queue.remember_asset(db, claimed, asset_id, created)
        return asset_id

    def _file_in_album(self, client: ImmichClient, claimed: Claim, asset_id: str) -> None:
        with self.store.connection() as db:
            album = upload_queue.album_id(db, claimed.run_id)
        if album is not None:
            try:
                client.add_to_album(album, asset_id)
                return
            except ImmichError as error:
                if error.code != "immich_rejected_400":  # "Album not found": deleted in Immich
                    raise
                with self.store.write() as db:
                    upload_queue.remember_album(db, claimed.run_id, None)
        album = client.find_album(claimed.run_id) or client.create_album(claimed.run_id)
        with self.store.write() as db:
            upload_queue.remember_album(db, claimed.run_id, album)
        client.add_to_album(album, asset_id)

    def _fail(self, claimed: Claim, code: str, *, transient: bool) -> None:
        _LOG.warning("Immich upload of %s failed: %s", claimed.library_id, code)
        now = self.store.clock()
        with self.store.write() as db:
            upload_queue.fail(
                db,
                self.store.contract,
                claimed,
                code,
                transient=transient,
                now=now,
                stamp=stamp(now),
                later=lambda delay: stamp(now + delay),
            )

    def _say(self, message: str) -> None:
        """Once per change, not once per attempt."""

        if message != self._complaint:
            self._complaint = message
            _LOG.warning("%s", message)

    def run(self, stop: threading.Event) -> None:
        """Until ``stop`` is set. An Immich that is away is tried less and less often."""

        self.stop = stop
        delay, pause = 0.0, 0.0
        while not stop.wait(delay):
            try:
                outcome = self.run_once()
            except Exception as error:  # the database or disk; the queue is still there later
                _LOG.error("Immich uploader stopped by %s", type(error).__name__)
                delay = _CRASH_S
                continue
            if outcome == "unavailable":
                pause = min(max(_PAUSE_FIRST_S, pause * 2), _PAUSE_LIMIT_S)
                delay = pause
            else:
                pause = 0.0
                delay = 0.0 if outcome == "done" else _IDLE_S
