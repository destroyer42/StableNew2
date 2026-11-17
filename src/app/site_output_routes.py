"""Typed media operations behind the existing native Site authentication."""

from __future__ import annotations

import json
import re
from typing import Any

from src.app.site_media_files import SiteOutputError
from src.app.site_output_catalog import SiteOutputCatalog

OUTPUT_STATUS = "/v1/output/status"
OUTPUT_LIBRARY = "/v1/output/library"
OUTPUT_PLAY = "/v1/output/play"
OUTPUT_CHUNK = "/v1/output/chunk"
OUTPUT_REVIEW = re.compile(r"/v1/output/review/(\d{8}_\d{6}_[A-Za-z0-9_-]{1,150})")
OUTPUT_RATING = re.compile(OUTPUT_REVIEW.pattern + "/rating")
_OUTPUT_IMAGE = re.compile(r"/v1/output/image/([a-f0-9]{32})")
_ID = re.compile(r"[a-f0-9]{32}")

_LIBRARY_FIELDS = {
    "search": {"field", "kind", "query", "offset", "revision", "refresh"},
    "thumbnails": {"ids"},
    "inspect": {"id"},
    "albums": set(),
    "album": {"id"},
    "save_album": {"id", "name", "items", "revision", "operation"},
    "rate": {"id", "digest", "score", "notes", "revision", "operation"},
}


def output_read(path: str) -> bool:
    return bool(
        path == OUTPUT_STATUS or OUTPUT_REVIEW.fullmatch(path) or _OUTPUT_IMAGE.fullmatch(path)
    )


def output_post(path: str) -> bool:
    return bool(
        path in {OUTPUT_LIBRARY, OUTPUT_PLAY, OUTPUT_CHUNK} or OUTPUT_RATING.fullmatch(path)
    )


def _unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise SiteOutputError("invalid_body")
        result[key] = value
    return result


def parse_body(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw, object_pairs_hook=_unique)
    except (ValueError, RecursionError) as exc:
        raise SiteOutputError("invalid_body") from exc
    if not isinstance(data, dict):
        raise SiteOutputError("invalid_body")
    return data


def read(catalog: SiteOutputCatalog, path: str) -> dict[str, Any] | tuple[str, bytes]:
    if path == OUTPUT_STATUS:
        return {"scope": catalog.scope, "review": True, "library": True, "range": True}
    if run := OUTPUT_REVIEW.fullmatch(path):
        return catalog.get_run(run[1], review=True)
    if match := _OUTPUT_IMAGE.fullmatch(path):
        item, raw, _digest = catalog.library.image(match[1])
        return item.mime, raw
    raise SiteOutputError("unknown_route")


def post(
    catalog: SiteOutputCatalog, path: str, body: dict[str, Any]
) -> dict[str, Any] | tuple[str, bytes]:
    catalog.require_active()
    if match := OUTPUT_RATING.fullmatch(path):
        return catalog.save_rating(match[1], body)
    if path in (OUTPUT_PLAY, OUTPUT_CHUNK):
        identifier = body.get("id")
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            raise SiteOutputError("unknown_media")
        if path == OUTPUT_PLAY and set(body) == {"id", "library"} and type(body["library"]) is bool:
            return catalog.open_video(identifier, library=body["library"])
        if (
            path == OUTPUT_CHUNK
            and set(body) == {"id", "start", "length"}
            and type(body["start"]) is int
            and type(body["length"]) is int
        ):
            return catalog.playback.chunk(identifier, body["start"], body["length"])
        raise SiteOutputError("invalid_range")
    if path != OUTPUT_LIBRARY:
        raise SiteOutputError("unknown_route")
    action = body.get("action")
    fields = _LIBRARY_FIELDS.get(action) if isinstance(action, str) else None
    if fields is None or set(body) != fields | {"action", "scope"}:
        raise SiteOutputError("invalid_library_request")
    if body["scope"] != catalog.scope:
        raise SiteOutputError("output_folder_changed")
    library = catalog.library
    if action == "search":
        return library.search(body)
    if action == "thumbnails":
        return {"thumbnails": library.thumbnails(body["ids"])}
    if action == "inspect":
        return library.inspect(body["id"])
    if action == "albums":
        return {"albums": library.albums()}
    if action == "album":
        return library.album(body["id"])
    if action == "save_album":
        return library.save_album(body)
    return library.rate(body)
