"""Browse Output and persist gallery records within one approved desktop grant."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import re
import sqlite3
import stat
import warnings
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Lock
from time import monotonic, time
from typing import Any
from weakref import ref as weakref

from PIL import Image, ImageOps, UnidentifiedImageError

from src.app import site_library_video
from src.app.site_library_index import LibraryIndex, index_for
from src.app.site_library_query import SOURCES, LibraryQuery, ratio_of, timestamp
from src.app.site_library_reconcile import Reconciliation, key_for, manifest_path, version_of
from src.app.site_media_files import SiteOutputError, checked_digest, inside, open_scoped
from src.app.site_rating_sync import edit_stamp, field_conflicts, root_identity, was_applied
from src.utils.atomic_io import atomic_write_bytes
from src.utils.image_metadata import (
    ImageMetadataContractV26,
    decode_payload,
    read_jpg_metadata,
    resolve_model_vae_fields,
    resolve_prompt_fields,
)
from src.utils.thread_registry import get_thread_registry

_STORAGE = ".stablenew-library"
_IMAGE_LIMIT = 32 * 1024 * 1024
_DOCUMENT_LIMIT = 512 * 1024
_METADATA_PROMPT_LIMIT = 65536
_POLL_SECONDS = 1.0
_RESCAN_SECONDS = 120.0
_WARM_COUNT = 200
_PREVIEW_VERSION = "grid-320-v1"
_MAX_PREVIEW_REQUESTS = 32
_IMAGE_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
_ID = re.compile(r"[a-f0-9]{32}")
_DIGEST = re.compile(r"[a-f0-9]{64}")
_RATING_RECEIPTS = "site_rating_receipts"
_GALLERY_WRITE_LOCK = Lock()
logger = logging.getLogger(__name__)


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _seed(value: object) -> str | None:
    if type(value) is int and 0 <= value < 2**64:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,20}", value):
        return _seed(int(value))
    return None


def _bounded_string(value: object, limit: int) -> str:
    return (
        value[:limit].encode("utf-8", "replace").decode("utf-8") if isinstance(value, str) else ""
    )


def _metadata_text(value: object) -> str | None:
    text = _bounded_string(value, 240).strip()
    if not text or text.casefold() in {"unknown", "unclassified"} or any(ord(c) < 32 for c in text):
        return None
    # Checkpoints may be recorded by absolute path. A catalogue exposes names only.
    return text.replace("\\", "/").rsplit("/", 1)[-1] or None


def _utc_text(value: int) -> str:
    return (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=value)).isoformat()


@dataclass(frozen=True)
class LibraryItem:
    path: str
    mime: str
    version: tuple[int, ...]
    width: int = 0
    height: int = 0
    prompt: str = ""
    tags: tuple[str, ...] = ()
    seed: str | None = None
    provenance: str = "unknown"
    canonical_id: str | None = None
    canonical_digest: str | None = None
    recorded_at: int | None = None
    family: str | None = None
    model: str | None = None
    workflow: str | None = None
    duration: float | None = None
    fps: float | None = None

    @property
    def kind(self) -> str:
        return self.mime.split("/")[0]

    @property
    def source(self) -> str:
        folder, slash, _ = self.path.partition("/")
        source = folder.casefold()
        return source if slash and source in SOURCES else "other"

    @property
    def orientation(self) -> str | None:
        if not self.width or not self.height:
            return None
        if self.width == self.height:
            return "square"
        return "portrait" if self.width < self.height else "landscape"

    @property
    def effective_time(self) -> int:
        return self.recorded_at if self.recorded_at is not None else self.version[3] // 1000

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> LibraryItem:
        body = json.loads(row["body"])
        body["version"] = tuple(body["version"])
        body["tags"] = tuple(body["tags"])
        return cls(**body)

    def row(self, sidecar: str, *, enriched: bool) -> tuple[Any, ...]:
        return (
            key_for(self.path),
            self.path,
            json.dumps(self.version),
            sidecar,
            self.kind,
            Path(self.path).name.casefold(),
            self.effective_time,
            self.source,
            self.width or None,
            self.height or None,
            ratio_of(self.width, self.height),
            self.orientation,
            self.family,
            self.model,
            self.workflow,
            self.model.casefold() if self.model else None,
            self.prompt.casefold(),
            json.dumps([tag.casefold() for tag in self.tags], ensure_ascii=False),
            self.seed,
            json.dumps(asdict(self), ensure_ascii=True),
            int(enriched),
            Path(self.path).parent.as_posix(),
        )

    def public(self, identifier: str) -> dict[str, Any]:
        return {
            "id": identifier,
            "name": Path(self.path).name,
            "mime": self.mime,
            "size": self.version[2],
            "width": self.width,
            "height": self.height,
            "prompt": self.prompt[:4096],
            "tags": self.tags,
            "seed": self.seed,
            "provenance": self.provenance,
            "source": self.source,
        }

    def browse(self, identifier: str, preview: str) -> dict[str, Any]:
        return {
            **self.public(identifier),
            "width": self.width or None,
            "height": self.height or None,
            "kind": self.kind,
            "modified_at": _utc_text(self.version[3] // 1000),
            "recorded_at": _utc_text(self.recorded_at) if self.recorded_at is not None else None,
            "timestamp": _utc_text(self.effective_time),
            "timestamp_basis": "recorded" if self.recorded_at is not None else "modified",
            "aspect_ratio": ratio_of(self.width, self.height),
            "orientation": self.orientation,
            "model_family": self.family,
            "model": self.model,
            "workflow": self.workflow,
            "duration": self.duration,
            "fps": self.fps,
            "preview": preview,
        }


@dataclass(frozen=True)
class Preview:
    mime: str
    data: bytes
    digest: str | None = None

    @property
    def ready(self) -> bool:
        return bool(self.data)

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


class OutputLibrary:
    def __init__(
        self,
        root: Path,
        scope: str,
        require_active: Callable[[], None],
        preview_idle: Callable[[], bool] = lambda: True,
    ) -> None:
        self.root = root
        self.scope = scope
        self.require_active = require_active
        self.preview_idle = preview_idle
        self.store = index_for(root)
        self._issued: dict[str, tuple[str, tuple[int, ...]]] = {}
        self._issued_lock = Lock()

    def close(self) -> None:
        with self.store.worker_lock:
            self.store.clients.discard(self)
            for key, (owner, _item) in tuple(self.store.requested.items()):
                if owner() is self:
                    self.store.requested.pop(key)
            self.store.wake.set()
        with self._issued_lock:
            self._issued.clear()

    def _issue(self, item: LibraryItem) -> str:
        key = key_for(item.path)
        identifier = hashlib.sha256(
            (self.scope + key + json.dumps(item.version)).encode()
        ).hexdigest()[:32]
        with self._issued_lock:
            # Browser-visible IDs can accumulate only to the inventory ceiling,
            # with a small allowance for active pages from prior revisions.
            if len(self._issued) >= 104_096 and identifier not in self._issued:
                self._issued.pop(next(iter(self._issued)))
            self._issued[identifier] = key, item.version
        return identifier

    def _id(self, relative: str) -> str:
        return self._registered(key_for(relative))

    def _registered(self, key: str) -> str:
        self.require_active()
        row = self.store.get(key)
        if row is None:
            with self.store.worker_lock:
                if self.store.scanning:
                    raise SiteOutputError("library_scanning")
            raise SiteOutputError("unknown_media")
        return self._issue(LibraryItem.from_row(row))

    def resolve_rating_target(self, target: object) -> str:
        if not isinstance(target, str) or not _ID.fullmatch(target):
            raise SiteOutputError("invalid_rating")
        self.start()
        return self._registered(target)

    def start(self, *, refresh: bool = False) -> None:
        self.require_active()
        store = self.store
        with store.worker_lock:
            store.clients.add(self)
            if refresh:
                store.refresh.set()
                store.scanning = True
                store.wake.set()
            if store.running:
                return
            store.running = store.scanning = True
            store.worker_error = False
            registry = get_thread_registry()
            cancel = Event()
            store.cancel = cancel

            def stop() -> None:
                cancel.set()
                store.wake.set()

            unsubscribe = registry.add_shutdown_listener(stop)

            def run() -> None:
                try:
                    OutputLibrary._reconcile(store, cancel)
                except (OSError, ValueError, sqlite3.Error):
                    with store.worker_lock:
                        store.worker_error = True
                    logger.exception("Output Library reconciliation failed")
                finally:
                    unsubscribe()
                    with store.worker_lock:
                        store.running = store.scanning = False
                        store.cancel = None
                        store.thread = None

            try:
                store.thread = registry.spawn(
                    target=run, name="Site Output index", purpose="Browse paired Output"
                )
            except RuntimeError:
                unsubscribe()
                store.running = store.scanning = False
                store.worker_error = True
                logger.exception("Could not start Output Library indexing")

    @staticmethod
    def _owner(store: LibraryIndex) -> OutputLibrary:
        with store.worker_lock:
            clients = tuple(store.clients)
        for client in clients:
            try:
                client.require_active()
            except SiteOutputError:
                continue
            return client
        raise SiteOutputError("output_folder_not_shared")

    @staticmethod
    def _reconcile(store: LibraryIndex, cancel: Event) -> None:
        def ensure_active() -> None:
            OutputLibrary._owner(store)
            if cancel.is_set():
                raise SiteOutputError("output_folder_not_shared")

        scan = Reconciliation(store)
        next_full = 0.0
        next_inventory = 0.0
        state = "incomplete"
        warmed: set[str] = set()
        warm_revision = -1
        warm_rows: list[sqlite3.Row] = []
        first = True
        pending = False
        while not cancel.is_set():
            try:
                owner = OutputLibrary._owner(store)
            except SiteOutputError:
                return
            try:
                now = monotonic()
                full = now >= next_full or store.refresh.is_set()
                if full or now >= next_inventory:
                    if full:
                        store.refresh.clear()
                        with store.worker_lock:
                            store.scanning = True
                    if first:
                        store.previews.enforce_budget()
                        first = False
                    result = scan.inventory(cancel, ensure_active, owner._basic, full=full)
                    if full:
                        next_full = monotonic() + _RESCAN_SECONDS
                    if full or result != "complete":
                        state = result
                    next_inventory = monotonic() + _POLL_SECONDS
                if cancel.is_set():
                    return
                serviced = owner._serve_preview_request(cancel)
                pending = owner._enrich(cancel, ensure_active) if not serviced else True
                visible = "reconciling" if pending or scan.unsettled else state
                if state == "error":
                    visible = state
                with store.connection() as db:
                    db.execute("UPDATE status SET state = ? WHERE state != ?", (visible, visible))
                with store.worker_lock:
                    store.scanning = visible == "reconciling" or store.refresh.is_set()
                    store.worker_error = state == "error"
                if (
                    store.previews.budget
                    and not serviced
                    and not cancel.is_set()
                    and owner.preview_idle()
                ):
                    with store.connection() as db:
                        revision = db.execute("SELECT revision FROM status").fetchone()[0]
                        if warm_revision != revision:
                            warm_revision = revision
                            warm_rows = list(
                                db.execute(
                                    "SELECT * FROM media WHERE enriched = 1 ORDER BY timestamp DESC, key LIMIT ?",
                                    (_WARM_COUNT,),
                                )
                            )
                            warmed.intersection_update(
                                row["version"] + row["key"] for row in warm_rows
                            )
                    for row in warm_rows:
                        warm_id = row["version"] + row["key"]
                        if warm_id in warmed:
                            continue
                        try:
                            if (
                                owner._preview(LibraryItem.from_row(row), warm=True, cancel=cancel)
                                is not None
                            ):
                                warmed.add(warm_id)
                        except (OSError, SiteOutputError):
                            warmed.add(warm_id)
                        break
            except SiteOutputError as error:
                if cancel.is_set():
                    return
                if str(error) != "output_folder_not_shared":
                    with store.worker_lock:
                        store.worker_error = True
                        store.scanning = False
                    return
                # A different catalogue for this root may still have an active grant.
                next_full = 0.0
            finally:
                del owner
            store.wake.wait(0.06 if pending or len(warmed) < len(warm_rows) else _POLL_SECONDS)
            store.wake.clear()

    def _basic(
        self, path: Path, mime: str, version: tuple[int, ...], sidecar: str
    ) -> tuple[Any, ...]:
        item = LibraryItem(path.relative_to(self.root).as_posix(), mime, version)
        return item.row(sidecar, enriched=False)

    def _enrich(self, cancel: Event, ensure_active: Callable[[], None]) -> bool:
        with self.store.connection() as db:
            pending = list(
                db.execute(
                    "SELECT * FROM media WHERE enriched = 0 AND (? OR kind = 'image') ORDER BY timestamp DESC, key LIMIT 128",
                    (self.preview_idle(),),
                )
            )
        if not pending:
            return False
        deadline = monotonic() + 0.10
        enriched = []
        for row in pending:
            if cancel.is_set():
                return True
            ensure_active()
            basic = LibraryItem.from_row(row)
            item = basic
            limit = _IMAGE_LIMIT if basic.kind == "image" else site_library_video.VIDEO_LIMIT
            if 0 < basic.version[2] <= limit:
                acquired = basic.kind != "video" or self.store.previews.lock.acquire(blocking=False)
                if not acquired:
                    break
                try:
                    path = self.path_for(basic)
                    item = self._metadata(path, basic, cancel=cancel)
                    self.path_for(basic)
                except (OSError, SiteOutputError):
                    item = basic
                finally:
                    if basic.kind == "video":
                        self.store.previews.lock.release()
            enriched.append(item.row(row["sidecar"], enriched=True))
            if monotonic() >= deadline:
                break
        if not cancel.is_set():
            ensure_active()
            with self.store.connection() as db:
                self.store.write_rows(db, enriched)
        return len(pending) == 128 or len(enriched) < len(pending)

    def _metadata(
        self, path: Path, basic: LibraryItem, *, cancel: Event | None = None
    ) -> LibraryItem:
        if basic.kind == "video":
            if not 0 < basic.version[2] <= site_library_video.VIDEO_LIMIT:
                return basic
            with open_scoped(self.root, path) as stream:
                if version_of(os.fstat(stream.fileno()))[:4] != basic.version[:4]:
                    return basic

                def stopped() -> bool:
                    return self._preview_cancelled(cancel)

                facts = site_library_video.probe(stream, stopped)
            payload = facts.pop("payload", {})
            return self._describe(
                replace(basic, **facts), payload, "embedded" if payload else "unknown"
            )
        if not 0 < basic.version[2] <= _IMAGE_LIMIT:
            return basic
        try:
            with open_scoped(self.root, path) as stream, warnings.catch_warnings():
                if version_of(os.fstat(stream.fileno()))[:4] != basic.version[:4]:
                    return basic
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(stream) as image:
                    if (
                        image.width * image.height > site_library_video.MAX_PIXELS
                        or _IMAGE_TYPES.get(image.format or "") != basic.mime
                    ):
                        return basic
                    width, height = image.size
                    fields = {
                        key: value
                        for key, value in image.info.items()
                        if isinstance(key, str) and isinstance(value, str)
                    }
                if basic.mime == "image/jpeg":
                    stream.seek(0)
                    fields.update(read_jpg_metadata(stream))
            basic = replace(basic, width=width, height=height)
            contract = ImageMetadataContractV26
            payload = (
                _dict(decode_payload(fields, max_decoded_bytes=contract.HARD_LIMIT_BYTES).payload)
                if fields.get(contract.KEY_SCHEMA) == contract.SCHEMA
                else {}
            )
            recorded = (
                fields.get(contract.KEY_CREATED_UTC)
                if fields.get(contract.KEY_SCHEMA) == contract.SCHEMA
                else None
            )
            if recorded:
                payload.setdefault("created_utc", recorded)
            if manifest := self._manifest(path, basic):
                item = self._describe(basic, manifest, "manifest")
                if item.recorded_at is None and recorded:
                    try:
                        return replace(item, recorded_at=timestamp(recorded))
                    except (ValueError, OverflowError):
                        return item
                return item
            if payload:
                return self._describe(basic, payload, "embedded")
            prompt, seed, tags = self._legacy(fields)
            return replace(
                basic,
                prompt=_bounded_string(prompt, _METADATA_PROMPT_LIMIT),
                tags=tuple(_bounded_string(tag, 120) for tag in tags[:32]),
                seed=seed,
                provenance="legacy" if prompt or seed is not None or tags else "unknown",
            )
        except (
            OSError,
            ValueError,
            RecursionError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ):
            return basic

    @staticmethod
    def _describe(basic: LibraryItem, payload: dict[str, Any], provenance: str) -> LibraryItem:
        if not payload:
            return basic
        generation = _dict(payload.get("generation"))
        stage = _dict(payload.get("stage_manifest"))
        artifact = _dict(payload.get("artifact"))
        sections = (artifact, stage, generation, payload)
        recorded = None
        for section in sections:
            for name in ("created_utc", "created_at", "generated_at", "timestamp"):
                try:
                    recorded = timestamp(section.get(name))
                    break
                except (ValueError, OverflowError):
                    continue
            if recorded is not None:
                break
        recorded_model, _vae = resolve_model_vae_fields(payload)
        family = next(
            (
                value
                for section in sections
                if (value := _metadata_text(section.get("model_family")))
            ),
            None,
        )
        model = _metadata_text(payload.get("model_id")) or _metadata_text(recorded_model)
        workflow = next(
            (
                value
                for section in sections
                if (value := _metadata_text(section.get("workflow_id")))
            ),
            None,
        )
        prompt, _negative = resolve_prompt_fields(payload)
        seed = next(
            (
                value
                for section in (stage, generation, payload)
                if (value := _seed(section.get("seed"))) is not None
            ),
            None,
        )
        tags = payload.get("tags", generation.get("tags"))
        return replace(
            basic,
            recorded_at=recorded,
            model=model,
            family=family,
            workflow=workflow,
            prompt=_bounded_string(prompt, _METADATA_PROMPT_LIMIT),
            seed=seed,
            provenance=provenance,
            tags=tuple(_bounded_string(tag, 120) for tag in tags[:32] if isinstance(tag, str))
            if isinstance(tags, list)
            else (),
            canonical_id=(_bounded_string(artifact.get("artifact_id"), 160) or None)
            if provenance == "manifest"
            else None,
            canonical_digest=(artifact.get("sha256") or payload.get("artifact_sha256"))
            if provenance == "manifest"
            else None,
        )

    def _manifest(self, path: Path, item: LibraryItem) -> dict[str, Any]:
        try:
            with open_scoped(self.root, manifest_path(path)) as stream:
                content = stream.read(_DOCUMENT_LIMIT + 1)
            data = _dict(json.loads(content)) if len(content) <= _DOCUMENT_LIMIT else {}
        except (OSError, ValueError, RecursionError):
            return {}
        artifact = _dict(data.get("artifact"))
        digest = artifact.get("sha256", data.get("artifact_sha256"))
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            return {}
        with open_scoped(self.root, path) as source:
            if version_of(os.fstat(source.fileno()))[:4] != item.version[:4]:
                return {}
            return data if digest == checked_digest(source, size_limit=_IMAGE_LIMIT) else {}

    @staticmethod
    def _legacy(fields: dict[str, str]) -> tuple[str, str | None, list[str]]:
        parameters = fields.get("parameters", "")
        prompt = re.split(r"\n(?:Negative prompt:|Steps:)", parameters, maxsplit=1)[0].strip()
        settings = parameters.rsplit("\n", 1)[-1]
        found = re.search(r"(?:^|, )Seed: ([0-9]{1,20})(?:,|$)", settings)
        tags = [
            part.strip()
            for part in re.split(r"[,;]", fields.get("tags", ""), maxsplit=32)
            if part.strip()
        ]
        return fields.get("prompt", prompt), _seed(found[1] if found else fields.get("seed")), tags

    def search(
        self, body: dict[str, Any], *, indexed: bool = False, facets: bool = False
    ) -> dict[str, Any]:
        query = LibraryQuery.parse(body, legacy=not indexed)
        self.start(refresh=query.refresh)
        identity = self.scope + query.identity()

        def revision(epoch: str, current: int) -> str:
            return hashlib.sha256(f"{identity}/{epoch}/{current}".encode()).hexdigest()[:32]

        self.store.check_root()
        rows, total, token, state, limited, pending, values = self.store.query(
            query, facets=facets, revision=revision
        )
        with self.store.worker_lock:
            scanning = self.store.scanning
            worker_error = self.store.worker_error
        if worker_error:
            state = "error"
        scanning = not worker_error and (
            scanning or state == "reconciling" or (state == "incomplete" and not limited) or pending
        )
        entries = []
        for row in rows:
            item = LibraryItem.from_row(row)
            try:
                self.path_for(item)
            except (OSError, SiteOutputError):
                continue
            entries.append(item)
        stale = len(entries) != len(rows)
        if indexed:
            keys = [self._preview_key(item, legacy=False) for item in entries]
            previews = self.store.previews.preview_states(keys)
            items = [
                item.browse(self._issue(item), previews.get(key, "pending"))
                for item, key in zip(entries, keys, strict=True)
            ]
        else:
            items = [item.public(self._issue(item)) for item in entries]
        self.require_active()
        payload = {
            "items": items,
            "total": total,
            "revision": token,
            "scanning": scanning,
            "limited": limited,
            "metadata_limited": pending,
            "scan_error": worker_error or state == "error",
        }
        if indexed:
            payload.update(
                state="reconciling" if scanning else state,
                partial=stale or scanning or state != "complete" or limited or pending,
                next_offset=query.offset + len(rows) if query.offset + len(rows) < total else None,
            )
        if facets:
            payload["facets"] = values
        return payload

    def item(self, identifier: object) -> LibraryItem:
        self.require_active()
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            raise SiteOutputError("unknown_media")
        with self._issued_lock:
            issued = self._issued.get(identifier)
        if issued is None or (row := self.store.get(issued[0])) is None:
            raise SiteOutputError("unknown_media")
        item = LibraryItem.from_row(row)
        if issued[1] != item.version:
            raise SiteOutputError("media_changed")
        return item

    def path_for(self, item: LibraryItem) -> Path:
        self.require_active()
        self.store.check_root()
        path = inside(self.root, self.root / item.path)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or version_of(info) != item.version:
            raise SiteOutputError("media_changed")
        return path

    def image(self, identifier: object) -> tuple[LibraryItem, bytes, str]:
        item = self.item(identifier)
        if item.kind != "image":
            raise SiteOutputError("unsupported_media")
        path = self.path_for(item)
        if not item.width:
            item = self._metadata(path, item)
        with open_scoped(self.root, path) as stream:
            if version_of(os.fstat(stream.fileno()))[:4] != item.version[:4]:
                raise SiteOutputError("media_changed")
            raw = stream.read(_IMAGE_LIMIT + 1)
        self.path_for(item)
        if len(raw) > _IMAGE_LIMIT:
            raise SiteOutputError("media_too_large")
        digest = hashlib.sha256(raw).hexdigest()
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if (
                    _IMAGE_TYPES.get(image.format or "") != item.mime
                    or image.width * image.height > site_library_video.MAX_PIXELS
                ):
                    raise SiteOutputError("unsupported_media")
                item = replace(item, width=image.width, height=image.height)
                image.verify()
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
            raise SiteOutputError("unsupported_media") from exc
        return item, raw, digest

    def _preview_key(self, item: LibraryItem, *, legacy: bool) -> str:
        variant = (
            "legacy-jpeg" if legacy else "poster-jpeg" if item.kind == "video" else "webp-or-jpeg"
        )
        return hashlib.sha256(
            json.dumps(
                (self.store.identity, item.path, item.version, _PREVIEW_VERSION, variant)
            ).encode()
        ).hexdigest()

    def _preview(
        self,
        item: LibraryItem,
        *,
        legacy: bool = False,
        warm: bool = False,
        cancel: Event | None = None,
    ) -> Preview | None:
        if legacy and item.kind != "image":
            raise SiteOutputError("unsupported_media")
        path = self.path_for(item)
        if item.kind == "video" and not 0 < item.version[2] <= site_library_video.VIDEO_LIMIT:
            return Preview("", b"")
        key = self._preview_key(item, legacy=legacy)

        def cached() -> Preview | None:
            row = self.store.previews.preview(key, touch=None if warm else int(time()))
            if row is None:
                return None
            result = Preview(row["mime"], row["data"], row["digest"])
            return result if result.checksum == row["checksum"] else None

        if result := cached():
            self.path_for(item)
            return result
        if not self.store.previews.lock.acquire(blocking=not warm):
            return None
        try:
            if result := cached():
                self.path_for(item)
                return result
            if cancel is not None and cancel.is_set():
                return None
            with open_scoped(self.root, path) as stream:
                if version_of(os.fstat(stream.fileno()))[:4] != item.version[:4]:
                    raise SiteOutputError("media_changed")
                if item.kind == "video":

                    def stopped() -> bool:
                        return self._preview_cancelled(cancel)

                    raw = site_library_video.poster(stream, item.duration, stopped)
                    result = Preview("image/jpeg", raw)
                elif 0 < item.version[2] <= _IMAGE_LIMIT:
                    digest = checked_digest(stream, size_limit=_IMAGE_LIMIT) if legacy else None
                    stream.seek(0)
                    result = self._encode_preview(stream, item.mime, legacy=legacy, digest=digest)
                else:
                    result = Preview("", b"")
            self.path_for(item)
            if cancel is not None and cancel.is_set():
                return None
            self.store.previews.put_preview(
                key,
                result.ready,
                result.mime,
                result.data,
                result.digest,
                result.checksum,
                int(time()),
            )
            return result
        finally:
            self.store.previews.lock.release()

    def _preview_cancelled(self, cancel: Event | None) -> bool:
        try:
            self.require_active()
        except SiteOutputError:
            return True
        return cancel is not None and cancel.is_set()

    @staticmethod
    def _encode_preview(
        stream: Any,
        mime: str,
        *,
        legacy: bool,
        digest: str | None,
    ) -> Preview:
        try:
            with Image.open(stream) as image:
                if (
                    _IMAGE_TYPES.get(image.format or "") != mime
                    or image.width * image.height > site_library_video.MAX_PIXELS
                ):
                    return Preview("", b"")
                image.thumbnail((site_library_video.EDGE, site_library_video.EDGE))
                rgb = ImageOps.exif_transpose(image).convert("RGB")
                output = io.BytesIO()
                if not legacy:
                    try:
                        rgb.save(output, "WEBP", quality=78, method=2)
                        return Preview("image/webp", output.getvalue())
                    except OSError:
                        output = io.BytesIO()
                rgb.save(output, "JPEG", quality=76)
                return Preview("image/jpeg", output.getvalue(), digest)
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError):
            return Preview("", b"")

    def _request_poster(self, item: LibraryItem) -> Preview | None:
        self.path_for(item)
        if not 0 < item.version[2] <= site_library_video.VIDEO_LIMIT:
            return Preview("", b"")
        key = self._preview_key(item, legacy=False)
        row = self.store.previews.preview(key, touch=int(time()))
        if row is not None:
            preview = Preview(row["mime"], row["data"])
            if preview.checksum == row["checksum"]:
                self.path_for(item)
                return preview
        if self.store.previews.budget <= 256:
            return Preview("", b"")
        self.start()
        with self.store.worker_lock:
            if (
                key not in self.store.requested
                and len(self.store.requested) < _MAX_PREVIEW_REQUESTS
            ):
                self.store.requested[key] = weakref(self), item
                self.store.wake.set()
        return None

    def _serve_preview_request(self, cancel: Event) -> bool:
        with self.store.worker_lock:
            if not self.store.requested:
                return False
            _, (owner_ref, item) = self.store.requested.popitem(last=False)
        owner = owner_ref()
        if owner is not None:
            try:
                owner._preview(item, cancel=cancel)
            except (OSError, SiteOutputError):
                logger.debug("Requested poster is unavailable")
        return True

    def thumbnails(self, items: object, *, indexed: bool = False) -> dict[str, dict[str, Any]]:
        if not isinstance(items, list) or len(items) > 8:
            raise SiteOutputError("invalid_library_request")
        result: dict[str, dict[str, Any]] = {}
        for identifier in items:
            try:
                item = self.item(identifier)
                preview = (
                    self._request_poster(item)
                    if indexed and item.kind == "video"
                    else self._preview(item, legacy=not indexed)
                )
            except (OSError, SiteOutputError):
                continue
            if preview is None:
                if indexed:
                    result[identifier] = {"state": "pending", "kind": item.kind}
                continue
            if indexed:
                result[identifier] = (
                    {
                        "state": "ready",
                        "mime": preview.mime,
                        "image": base64.b64encode(preview.data).decode("ascii"),
                    }
                    if preview.ready
                    else {"state": "placeholder", "kind": item.kind}
                )
            elif preview.ready and preview.digest is not None:
                try:
                    rating = self._read_rating(item, preview.digest)
                except (OSError, SiteOutputError):
                    rating = {}
                result[identifier] = {
                    "image": base64.b64encode(preview.data).decode("ascii"),
                    "score": rating.get("score"),
                }
        self.require_active()
        return result

    def _folder(self, kind: str, *, create: bool = False) -> Path:
        path = self.root
        for name in (_STORAGE, kind):
            path /= name
            if create:
                path.mkdir(exist_ok=True)
            inside(self.root, path)
        return path

    def _document(self, path: Path, schema: str) -> dict[str, Any]:
        try:
            with open_scoped(self.root, path) as stream:
                raw = stream.read(_DOCUMENT_LIMIT + 1)
        except FileNotFoundError:
            return {}
        try:
            value = _dict(json.loads(raw)) if len(raw) <= _DOCUMENT_LIMIT else {}
        except (ValueError, RecursionError) as exc:
            raise SiteOutputError("library_record_invalid") from exc
        if value.get("schema") != schema or type(value.get("revision")) is not int:
            raise SiteOutputError("library_record_version")
        return value

    @staticmethod
    def _mutation(body: dict[str, Any]) -> tuple[int, str, str]:
        expected, operation = body.get("revision"), body.get("operation")
        if (
            type(expected) is not int
            or not isinstance(operation, str)
            or not _ID.fullmatch(operation)
        ):
            raise SiteOutputError("invalid_library_request")
        encoded = json.dumps(body, ensure_ascii=False, sort_keys=True).encode()
        return expected, operation, hashlib.sha256(encoded).hexdigest()

    def _save(
        self,
        path: Path,
        record: dict[str, Any],
        mutation: tuple[int, str, str],
        *,
        base: dict[str, Any] | None = None,
        stamp: dict[str, str] | None = None,
        before_replace: Callable[[], Any] | None = None,
    ) -> dict[str, Any]:
        expected, operation, payload_hash = mutation
        with _GALLERY_WRITE_LOCK:
            previous = self._document(path, record["schema"])
            receipts = previous.get(_RATING_RECEIPTS, {})
            if not isinstance(receipts, dict):
                raise SiteOutputError("library_record_invalid")
            if stamp is not None and base is not None:
                if was_applied(receipts, operation, stamp):
                    return self._public_rating(previous)
                current = {"score": previous.get("score"), "notes": previous.get("notes", "")}
                patch = {key: record[key] for key in base}
                if conflicts := field_conflicts(current, base, patch):
                    return {"conflict": conflicts, "revision": previous.get("revision", 0)}
                record = {**record, **current, **patch}
                receipts = {**receipts, operation: stamp}
                expected = previous.get("revision", 0)
            elif previous.get("operation") == operation:
                if previous.get("operation_digest") == payload_hash:
                    return self._public_rating(previous)
                raise SiteOutputError("library_conflict")
            if previous.get("revision", 0) != expected:
                raise SiteOutputError("library_conflict")
            inside(self.root, path.parent)
            if path.exists() or path.is_symlink():
                inside(self.root, path)
            now = datetime.now(UTC).isoformat()
            stamped = {
                **record,
                "revision": expected + 1,
                "operation": operation,
                "operation_digest": payload_hash,
                "updated_at": now,
                "created_at": previous.get("created_at", now),
            }
            if receipts:
                stamped[_RATING_RECEIPTS] = receipts
            encoded = json.dumps(stamped, ensure_ascii=False, indent=2).encode()
            if len(encoded) > _DOCUMENT_LIMIT:
                raise SiteOutputError("library_record_too_large")
            if before_replace is not None:
                before_replace()
            self.require_active()
            atomic_write_bytes(path, encoded)
            if self._document(path, record["schema"]) != stamped:
                raise SiteOutputError("library_conflict")
            return self._public_rating(stamped)

    @staticmethod
    def _public_rating(record: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in record.items() if key != _RATING_RECEIPTS}

    def inspect(self, identifier: object) -> dict[str, Any]:
        item, _raw, digest = self.image(identifier)
        rating = self._read_rating(item, digest)
        return {
            "item": item.public(str(identifier)),
            "digest": digest,
            "rating": self._public_rating(rating),
            "rating_target": key_for(item.path),
            "prompt": item.prompt,
        }

    def review_results(
        self, identifier: object, digest: object, resolve: Callable[[str], Sequence[str]]
    ) -> list[dict[str, Any]]:
        original, _raw, verified = self.image(identifier)
        if verified != digest:
            raise SiteOutputError("media_changed")
        results = []
        for output in resolve(verified)[:12]:
            self.require_active()
            path = Path(output).absolute()
            if path == self.root / original.path or not path.is_relative_to(self.root):
                continue
            child_id = self._id(path.relative_to(self.root).as_posix())
            try:
                item, _bytes, child_digest = self.image(child_id)
                if self.path_for(item) != path:
                    continue
            except (OSError, SiteOutputError):
                continue
            results.append({"item": item.public(child_id), "digest": child_digest})
        return results

    def _read_rating(self, item: LibraryItem, digest: str) -> dict[str, Any]:
        try:
            path = self._folder("ratings") / f"{key_for(item.path)}-{digest}.rating.json"
            return self._document(path, "stablenew.output-rating.v1")
        except FileNotFoundError:
            return {}

    def rate(self, body: dict[str, Any]) -> dict[str, Any]:
        item, _raw, digest = self.image(body.get("id"))
        if body.get("digest") != digest:
            raise SiteOutputError("media_changed")
        score, notes = body.get("score"), body.get("notes")
        if not self._valid_score(score) or not self._valid_notes(notes):
            raise SiteOutputError("invalid_rating")
        record = {
            "schema": "stablenew.output-rating.v1",
            "sha256": digest,
            "score": score,
            "notes": notes,
        }
        path = self._folder("ratings", create=True) / f"{key_for(item.path)}-{digest}.rating.json"
        return self._save(path, record, self._mutation(body))

    @staticmethod
    def _valid_score(value: object) -> bool:
        return value is None or (type(value) is int and 1 <= value <= 5)

    @staticmethod
    def _valid_notes(value: object) -> bool:
        return isinstance(value, str) and len(value) <= 8000

    def sync_rating(self, body: dict[str, Any]) -> dict[str, Any]:
        if body["root"] != root_identity(self.root):
            raise SiteOutputError("output_folder_changed")
        base, changes = body["base"], body["changes"]
        validators = {"score": self._valid_score, "notes": self._valid_notes}
        if (
            not isinstance(base, dict)
            or not isinstance(changes, dict)
            or not changes
            or base.keys() != changes.keys()
            or not changes.keys() <= validators.keys()
            or any(
                not validators[key](value)
                for fields in (base, changes)
                for key, value in fields.items()
            )
            or type(body["revision"]) is not int
            or body["revision"] < 0
        ):
            raise SiteOutputError("invalid_rating")
        stamp = edit_stamp(
            body["operation"],
            body["actor_time"],
            {key: value for key, value in body.items() if key != "scope"},
        )
        identifier = self.resolve_rating_target(body["target"])
        item, _raw, digest = self.image(identifier)
        if body["digest"] != digest:
            raise SiteOutputError("media_changed")
        record = {"schema": "stablenew.output-rating.v1", "sha256": digest, **changes}
        self.require_active()
        path = self._folder("ratings", create=True) / f"{key_for(item.path)}-{digest}.rating.json"
        return self._save(
            path,
            record,
            (body["revision"], body["operation"], stamp["digest"]),
            base=base,
            stamp=stamp,
            before_replace=lambda: self.path_for(item),
        )

    def albums(self) -> list[dict[str, Any]]:
        try:
            folder = self._folder("albums")
        except FileNotFoundError:
            return []
        albums = []
        for path in sorted(folder.glob("*.album.json"))[:500]:
            identifier = path.name.removesuffix(".album.json")
            if not _ID.fullmatch(identifier):
                continue
            try:
                data = self._document(path, "stablenew.output-album.v1")
                albums.append(
                    {"id": identifier, "name": data["name"], "revision": data["revision"]}
                )
            except (SiteOutputError, OSError, KeyError):
                albums.append({"id": identifier, "name": "Unavailable album", "unavailable": True})
        return albums

    def album(self, identifier: object) -> dict[str, Any]:
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            raise SiteOutputError("invalid_library_request")
        album = self._document(
            self._folder("albums") / f"{identifier}.album.json", "stablenew.output-album.v1"
        )
        if not album:
            raise SiteOutputError("library_record_missing")
        if not isinstance(album.get("items"), list) or len(album["items"]) > 120:
            raise SiteOutputError("library_record_invalid")
        result = []
        for position, ref in enumerate(album["items"]):
            relative = _dict(ref).get("path")
            if not isinstance(relative, str):
                raise SiteOutputError("library_record_invalid")
            try:
                key = self._id(relative)
                item, raw, digest = self.image(key)
                if digest != ref.get("sha256"):
                    raise SiteOutputError("media_changed")
                result.append(
                    {
                        **item.public(key),
                        "position": position,
                        "download": {
                            "bytes": len(raw),
                            "digest": digest,
                            "rating_target": key_for(item.path),
                        },
                    }
                )
            except (OSError, SiteOutputError):
                result.append(
                    {"position": position, "name": Path(relative).name, "unavailable": True}
                )
        return {
            "id": identifier,
            "name": album["name"],
            "revision": album["revision"],
            "items": result,
        }

    def save_album(self, body: dict[str, Any]) -> dict[str, Any]:
        identifier, name, refs = (body.get(key) for key in ("id", "name", "items"))
        if (
            not isinstance(identifier, str)
            or not _ID.fullmatch(identifier)
            or not isinstance(name, str)
            or not 0 < len(name.strip()) <= 120
            or not isinstance(refs, list)
            or len(refs) > 120
        ):
            raise SiteOutputError("invalid_library_request")
        path = self._folder("albums", create=True) / f"{identifier}.album.json"
        mutation = self._mutation(body)
        current = self._document(path, "stablenew.output-album.v1")
        if (
            current.get("operation") == mutation[1]
            and current.get("operation_digest") == mutation[2]
        ):
            return {"id": identifier, "name": current["name"], "revision": current["revision"]}
        previous = current.get("items", [])
        items = []
        used = set()
        for ref in refs:
            if type(ref) is int and 0 <= ref < len(previous):
                value = previous[ref]
            elif isinstance(ref, str):
                item, _raw, digest = self.image(ref)
                canonical = item.canonical_id if item.canonical_digest == digest else None
                value = {"path": item.path, "sha256": digest, "canonical_id": canonical}
            else:
                raise SiteOutputError("invalid_library_request")
            if value["path"] in used:
                raise SiteOutputError("invalid_library_request")
            used.add(value["path"])
            items.append(value)
        record = {
            "schema": "stablenew.output-album.v1",
            "id": identifier,
            "name": name.strip(),
            "items": items,
        }
        saved = self._save(path, record, mutation)
        return {"id": identifier, "name": saved["name"], "revision": saved["revision"]}
