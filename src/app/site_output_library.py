"""Browse Output and persist gallery records within one approved desktop grant."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import re
import secrets
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock
from time import monotonic
from typing import Any

from PIL import Image, UnidentifiedImageError

from src.app.site_media_files import (
    MEDIA_TYPES,
    SiteOutputError,
    checked_digest,
    inside,
    is_link,
    open_scoped,
)
from src.app.site_rating_sync import edit_stamp, field_conflicts, root_identity, was_applied
from src.utils.atomic_io import atomic_write_bytes
from src.utils.image_metadata import (
    ImageMetadataContractV26,
    decode_payload,
    read_jpg_metadata,
    resolve_prompt_fields,
)
from src.utils.thread_registry import get_thread_registry

_STORAGE = ".stablenew-library"
_IMAGE_LIMIT = 32 * 1024 * 1024
_SEARCH_LIMIT = 100_000
_ENTRY_LIMIT = 250_000
_METADATA_BUDGET = 128 * 1024 * 1024
_SOURCE_ORDER = {
    "image": ("pipeline", "learning", "reprocess", "movie_clips", "svd", "video_eval", "other"),
    "video": ("movie_clips", "svd", "reprocess", "pipeline", "learning", "video_eval", "other"),
}
SOURCES = frozenset(_SOURCE_ORDER["image"])
_SCAN_FIRST = ("pipeline", "movie_clips", "svd", "learning", "reprocess", "video_eval")
logger = logging.getLogger(__name__)
_DOCUMENT_LIMIT = 512 * 1024
# Catalog grants have separate identifiers but can write the same native record.
_GALLERY_WRITE_LOCK = Lock()
_IMAGE_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
_ID = re.compile(r"[a-f0-9]{32}")
_DIGEST = re.compile(r"[a-f0-9]{64}")
_RATING_RECEIPTS = "site_rating_receipts"


def _key(relative: str) -> str:
    return hashlib.sha256(os.path.normcase(relative).encode()).hexdigest()[:32]


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _seed(value: object) -> str | None:
    if type(value) is int and 0 <= value < 2**64:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,20}", value):
        return _seed(int(value))
    return None


def _bounded_string(value: object, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


@dataclass(frozen=True)
class LibraryItem:
    path: str
    mime: str
    version: tuple[int, int, int, int]
    width: int = 0
    height: int = 0
    prompt: str = ""
    tags: tuple[str, ...] = ()
    seed: str | None = None
    provenance: str = "unknown"
    canonical_id: str | None = None

    @property
    def source(self) -> str:
        folder, slash, _ = self.path.partition("/")
        source = folder.casefold()
        return source if slash and source in SOURCES else "other"

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


def _version(status: os.stat_result) -> tuple[int, int, int, int]:
    return status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns


@dataclass
class Index:
    items: dict[str, LibraryItem] = field(default_factory=dict)
    revision: str = field(default_factory=lambda: secrets.token_hex(16))
    metadata_revision: str = field(default_factory=lambda: secrets.token_hex(16))
    scanning: bool = False
    limited: bool = False
    metadata_limited: bool = False
    error: bool = False


class OutputLibrary:
    def __init__(self, root: Path, scope: str, require_active: Callable[[], None]) -> None:
        self.root = root
        self.scope = scope
        self.require_active = require_active
        self.index = Index()
        self._lock = Lock()
        self._started = False
        self._scan_cancel: Event | None = None

    def close(self) -> None:
        with self._lock:
            if self._scan_cancel is not None:
                self._scan_cancel.set()
            self.index = Index()

    def _id(self, relative: str) -> str:
        return self._scoped_id(_key(relative))

    def _scoped_id(self, target: str) -> str:
        return hashlib.sha256((self.scope + target).encode()).hexdigest()[:32]

    def resolve_rating_target(self, target: object) -> str:
        if not isinstance(target, str) or not _ID.fullmatch(target):
            raise SiteOutputError("invalid_rating")
        self.start()
        identifier = self._scoped_id(target)
        with self._lock:
            if identifier in self.index.items:
                return identifier
            if self.index.scanning:
                raise SiteOutputError("library_scanning")
        raise SiteOutputError("unknown_media")

    def _metadata(
        self, path: Path, relative: str, mime: str, version: tuple[int, int, int, int]
    ) -> LibraryItem:
        basic = LibraryItem(relative, mime, version)
        if not mime.startswith("image/") or version[2] > _IMAGE_LIMIT:
            return basic
        try:
            with open_scoped(self.root, path) as stream, warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(stream) as image:
                    if (
                        image.width * image.height > 64_000_000
                        or _IMAGE_TYPES.get(image.format or "") != mime
                    ):
                        return basic
                    width, height = image.size
                    fields = {
                        key: value for key, value in image.info.items() if isinstance(value, str)
                    }
                if mime == "image/jpeg":
                    stream.seek(0)
                    fields.update(read_jpg_metadata(stream))
            contract = ImageMetadataContractV26
            payload = (
                _dict(decode_payload(fields, max_decoded_bytes=contract.HARD_LIMIT_BYTES).payload)
                if fields.get(contract.KEY_SCHEMA) == contract.SCHEMA
                else {}
            )
            provenance = "embedded" if payload else "unknown"
            manifest = self._manifest(path)
            if manifest:
                payload, provenance = manifest, "manifest"
            if payload:
                generation = _dict(payload.get("generation"))
                stage = _dict(payload.get("stage_manifest"))
                prompt, _ = resolve_prompt_fields(payload)
                seed = next(
                    (
                        value
                        for section in (stage, generation, payload)
                        if (value := _seed(section.get("seed"))) is not None
                    ),
                    None,
                )
                tags = payload.get("tags", generation.get("tags"))
            else:
                prompt, seed, tags = self._legacy(fields)
                provenance = "legacy" if prompt or seed is not None or tags else "unknown"
            tag_values = (
                tuple(_bounded_string(value, 120) for value in tags[:32] if isinstance(value, str))
                if isinstance(tags, list)
                else ()
            )
            return LibraryItem(
                relative,
                mime,
                version,
                width,
                height,
                _bounded_string(prompt, 65536),
                tag_values,
                seed,
                provenance,
                _bounded_string(_dict(manifest.get("artifact")).get("artifact_id"), 160) or None,
            )
        except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            return basic

    def _manifest(self, path: Path) -> dict[str, Any]:
        candidate = path.parent / "manifests" / (path.stem + ".json")
        try:
            with open_scoped(self.root, candidate) as stream:
                content = stream.read(_DOCUMENT_LIMIT + 1)
            data = _dict(json.loads(content)) if len(content) <= _DOCUMENT_LIMIT else {}
        except (OSError, ValueError, RecursionError):
            return {}
        artifact = _dict(data.get("artifact"))
        digest = artifact.get("sha256", data.get("artifact_sha256"))
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            return {}
        with open_scoped(self.root, path) as source:
            if source.seek(0, 2) > _IMAGE_LIMIT:
                return {}
            source.seek(0)
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

    def _publish(
        self,
        items: dict[str, LibraryItem],
        *,
        scanning: bool,
        limited: bool,
        error: bool,
        inventory_revision: str | None = None,
        metadata_limited: bool = False,
    ) -> None:
        with self._lock:
            self.require_active()
            self.index = Index(
                items,
                scanning=scanning,
                limited=limited,
                error=error,
                metadata_limited=metadata_limited,
            )
            if inventory_revision is not None:
                self.index.revision = inventory_revision

    @staticmethod
    def _sort_key(entry: tuple[str, LibraryItem]) -> tuple[int, int, str]:
        item = entry[1]
        sources = _SOURCE_ORDER[item.mime.split("/")[0]]
        return sources.index(item.source), -item.version[3], item.path

    def _inventory(self, cancel: Event) -> tuple[dict[str, LibraryItem], bool, bool]:
        items: dict[str, LibraryItem] = {}
        limited = False
        error = False
        visited = 0
        next_publish = monotonic() + 1
        published = 0

        def walk_error(_error: OSError) -> None:
            nonlocal error
            error = True

        for parent, directories, files in os.walk(
            self.root, topdown=True, onerror=walk_error, followlinks=False
        ):
            if cancel.is_set():
                break
            self.require_active()
            try:
                directory = inside(self.root, Path(parent))
            except (OSError, SiteOutputError):
                directories.clear()
                error = True
                continue
            allowed = []
            for name in directories:
                try:
                    if name.casefold() != _STORAGE and not is_link((directory / name).lstat()):
                        allowed.append(name)
                except OSError:
                    error = True
            if directory == self.root:
                allowed.sort(
                    key=lambda name: (
                        _SCAN_FIRST.index(name.casefold())
                        if name.casefold() in _SCAN_FIRST
                        else len(_SCAN_FIRST),
                        name.casefold(),
                    )
                )
            directories[:] = allowed
            for name in files:
                if cancel.is_set():
                    break
                self.require_active()
                visited += 1
                if visited > _ENTRY_LIMIT or len(items) >= _SEARCH_LIMIT:
                    limited = True
                    break
                path = directory / name
                mime = MEDIA_TYPES.get(path.suffix.lower())
                if mime is None or name.startswith("."):
                    continue
                try:
                    info = path.lstat()
                except OSError:
                    error = True
                    continue
                if is_link(info):
                    continue
                relative = path.relative_to(self.root).as_posix()
                items[self._id(relative)] = LibraryItem(relative, mime, _version(info))
                if (published == 0 and len(items) == 24) or monotonic() >= next_publish:
                    snapshot = dict(sorted(items.items(), key=self._sort_key))
                    self._publish(snapshot, scanning=True, limited=False, error=error)
                    published = len(items)
                    next_publish = monotonic() + 1
            if limited:
                break
        return dict(sorted(items.items(), key=self._sort_key)), limited, error

    def _scan(self, cancel: Event) -> None:
        inventory, limited, error = self._inventory(cancel)
        if cancel.is_set():
            return
        self._publish(inventory, scanning=True, limited=limited, error=error)
        with self._lock:
            revision = self.index.revision
        items = inventory.copy()
        metadata_bytes = 0
        metadata_limited = False
        next_publish = monotonic() + 2
        for key, basic in inventory.items():
            if cancel.is_set():
                return
            self.require_active()
            if not basic.mime.startswith("image/"):
                continue
            item = self._metadata(self.root / basic.path, basic.path, basic.mime, basic.version)
            metadata_bytes += 4 * (len(item.prompt) + sum(map(len, item.tags)))
            if metadata_bytes > _METADATA_BUDGET:
                metadata_limited = True
                break
            items[key] = item
            if monotonic() >= next_publish:
                self._publish(
                    items.copy(),
                    scanning=True,
                    limited=limited,
                    error=error,
                    inventory_revision=revision,
                )
                next_publish = monotonic() + 2
        self._publish(
            items,
            scanning=False,
            limited=limited,
            error=error,
            inventory_revision=revision,
            metadata_limited=metadata_limited,
        )

    def start(self, *, refresh: bool = False) -> None:
        with self._lock:
            if self.index.scanning or (self._started and not refresh):
                return
            self.index.scanning = True
            self._started = True
            registry = get_thread_registry()
            cancel = Event()
            self._scan_cancel = cancel
            remove_listener = registry.add_shutdown_listener(cancel.set)

            def run_scan() -> None:
                try:
                    self._scan(cancel)
                except SiteOutputError:
                    logger.info("Output library grant ended during indexing")
                except (OSError, ValueError, TypeError, RuntimeError):
                    logger.exception("Output library indexing failed")
                finally:
                    remove_listener()
                    with self._lock:
                        if self._scan_cancel is cancel and self.index.scanning:
                            self.index.scanning = False
                            self.index.error = True

            try:
                registry.spawn(
                    target=run_scan, name="Site Output index", purpose="Browse paired Output"
                )
            except RuntimeError:
                remove_listener()
                self.index.scanning = False
                self.index.error = True
                logger.exception("Could not start Output library indexing")

    @staticmethod
    def _match(item: LibraryItem, field: str, query: str) -> bool:
        if not query:
            return True
        fields = {
            "name": (Path(item.path).name,),
            "tag": item.tags,
            "prompt": (item.prompt,),
        }
        seed_match = query == item.seed
        if field == "seed":
            return seed_match
        values = (
            (*fields["name"], *fields["tag"], *fields["prompt"])
            if field == "all"
            else fields[field]
        )
        return (field == "all" and seed_match) or any(query in text.casefold() for text in values)

    def search(self, body: dict[str, Any]) -> dict[str, Any]:
        field, kind, query, offset = (body.get(key) for key in ("field", "kind", "query", "offset"))
        source = body.get("source", "")
        if (
            field not in ("all", "name", "tag", "prompt", "seed")
            or kind not in ("image", "video")
            or not isinstance(query, str)
            or len(query) > 240
            or type(offset) is not int
            or not 0 <= offset <= _SEARCH_LIMIT
            or type(body.get("refresh")) is not bool
            or not isinstance(source, str)
            or (source and source not in SOURCES)
        ):
            raise SiteOutputError("invalid_library_request")
        query = query.strip().casefold()
        needs_metadata = bool(
            query and field in ("all", "tag", "prompt", "seed") and kind == "image"
        )
        self.start(refresh=body["refresh"])
        with self._lock:
            items, revision, scanning, limited, metadata_limited, error = (
                self.index.items,
                self.index.metadata_revision if needs_metadata else self.index.revision,
                self.index.scanning,
                self.index.limited,
                self.index.metadata_limited,
                self.index.error,
            )
        if offset and body.get("revision") != revision:
            raise SiteOutputError("stale_library_page")
        if field == "seed" and query:
            query = _seed(query) or "\0"
        matches = [
            (key, item)
            for key, item in items.items()
            if item.mime.startswith(kind + "/")
            and (not source or item.source == source)
            and self._match(item, field, query)
        ]
        return {
            "items": [item.public(key) for key, item in matches[offset : offset + 24]],
            "total": len(matches),
            "revision": revision,
            "scanning": scanning,
            "limited": limited,
            "metadata_limited": metadata_limited,
            "scan_error": error,
        }

    def item(self, identifier: object) -> LibraryItem:
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            raise SiteOutputError("unknown_media")
        with self._lock:
            item = self.index.items.get(identifier)
        if item is None:
            raise SiteOutputError("unknown_media")
        return item

    def path_for(self, item: LibraryItem) -> Path:
        path = inside(self.root, self.root / item.path)
        if _version(path.stat()) != item.version:
            raise SiteOutputError("media_changed")
        return path

    def image(self, identifier: object, *, thumb: bool = False) -> tuple[LibraryItem, bytes, str]:
        item = self.item(identifier)
        if not item.mime.startswith("image/"):
            raise SiteOutputError("unsupported_media")
        if not thumb and not item.width:
            item = self._metadata(self.path_for(item), item.path, item.mime, item.version)
        with open_scoped(self.root, self.path_for(item)) as stream:
            raw = stream.read(_IMAGE_LIMIT + 1)
        self.path_for(item)
        if len(raw) > _IMAGE_LIMIT:
            raise SiteOutputError("media_too_large")
        digest = hashlib.sha256(raw).hexdigest()
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if (
                    _IMAGE_TYPES.get(image.format or "") != item.mime
                    or image.width * image.height > 64_000_000
                ):
                    raise SiteOutputError("unsupported_media")
                if thumb:
                    image.thumbnail((320, 240))
                    output = io.BytesIO()
                    image.convert("RGB").save(output, "JPEG", quality=76)
                    return item, output.getvalue(), digest
                item = replace(item, width=image.width, height=image.height)
                image.verify()
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
            raise SiteOutputError("unsupported_media") from exc
        return item, raw, digest

    def thumbnails(self, items: object) -> dict[str, dict[str, Any]]:
        if not isinstance(items, list) or len(items) > 8:
            raise SiteOutputError("invalid_library_request")
        result = {}
        for identifier in items:
            try:
                item, raw, digest = self.image(identifier, thumb=True)
            except (OSError, SiteOutputError):
                continue
            try:
                rating = self._read_rating(item, digest)
            except (OSError, SiteOutputError):
                rating = {}
            result[identifier] = {
                "image": base64.b64encode(raw).decode("ascii"),
                "score": rating.get("score"),
            }
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
            "rating_target": _key(item.path),
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
            path = self._folder("ratings") / f"{_key(item.path)}-{digest}.rating.json"
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
        path = self._folder("ratings", create=True) / f"{_key(item.path)}-{digest}.rating.json"
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
        path = self._folder("ratings", create=True) / f"{_key(item.path)}-{digest}.rating.json"
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
                            "rating_target": _key(item.path),
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
                value = {"path": item.path, "sha256": digest, "canonical_id": item.canonical_id}
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
