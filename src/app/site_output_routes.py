"""Typed media operations behind the existing native Site authentication."""

from __future__ import annotations

import json
import re
from typing import Any

from src.app.site_media_files import SiteOutputError
from src.app.site_output_catalog import SiteOutputCatalog
from src.app.site_rating_sync import root_identity

OUTPUT_STATUS = "/v1/output/status"
OUTPUT_LIBRARY = "/v1/output/library"
OUTPUT_PLAY = "/v1/output/play"
OUTPUT_CHUNK = "/v1/output/chunk"
OUTPUT_REVIEW = re.compile(r"/v1/output/review/(\d{8}_\d{6}_[A-Za-z0-9_-]{1,150})")
OUTPUT_RATING = re.compile(OUTPUT_REVIEW.pattern + "/rating")
NATIVE_REVIEW_ACTIONS = frozenset({"native_review", "native_review_sync"})
_OUTPUT_IMAGE = re.compile(r"/v1/output/image/([a-f0-9]{32})")
_ID = re.compile(r"[a-f0-9]{32}")

_LIBRARY_FIELDS = {
    "search": {"field", "kind", "query", "offset", "revision", "refresh"},
    "thumbnails": {"ids"},
    "query_v2": set(),
    "facets_v2": set(),
    "previews_v2": {"ids"},
    "inspect": {"id"},
    "review_results": {"id", "digest"},
    "native_review": {"id", "digest"},
    "native_review_sync": {
        "target",
        "root",
        "digest",
        "section",
        "base",
        "changes",
        "revision",
        "operation",
        "actor_time",
    },
    "albums": set(),
    "album": {"id"},
    "save_album": {"id", "name", "items", "revision", "operation"},
    "rate": {"id", "digest", "score", "notes", "revision", "operation"},
    "rating_sync": {
        "target",
        "root",
        "digest",
        "base",
        "changes",
        "revision",
        "operation",
        "actor_time",
    },
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
        return {
            "scope": catalog.scope,
            "review": True,
            "library": True,
            "range": True,
            "library_sources": True,
            "library_index_v2": True,
            "rating_root": root_identity(catalog.library.root),
            "review_results": catalog.review_outputs is not None,
            "native_review": catalog.native_review is not None,
        }
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
    optional = {"source"} if action == "search" else set()
    if action in ("query_v2", "facets_v2"):
        optional = {"kind", "field", "query", "sort", "filters", "offset", "revision", "refresh"}
    if fields is None or set(body) - optional != fields | {"action", "scope"}:
        raise SiteOutputError("invalid_library_request")
    if body["scope"] != catalog.scope:
        raise SiteOutputError("output_folder_changed")
    library = catalog.library
    if action == "search":
        return library.search(body)
    if action in ("query_v2", "facets_v2"):
        return library.search(body, indexed=True, facets=action == "facets_v2")
    if action == "previews_v2":
        return {"previews": library.thumbnails(body["ids"], indexed=True)}
    if action == "thumbnails":
        return {"thumbnails": library.thumbnails(body["ids"])}
    if action == "inspect":
        return library.inspect(body["id"])
    if action in NATIVE_REVIEW_ACTIONS:
        if catalog.native_review is None:
            raise SiteOutputError("phone_scope_refused")
        if action == "native_review":
            return catalog.native_review.inspect(body["id"], body["digest"])
        return catalog.native_review.sync(body)
    if action == "review_results":
        if catalog.review_outputs is None:
            raise SiteOutputError("unknown_route")
        return {
            "results": library.review_results(body["id"], body["digest"], catalog.review_outputs)
        }
    if action == "albums":
        return {"albums": library.albums()}
    if action == "album":
        return library.album(body["id"])
    if action == "save_album":
        return library.save_album(body)
    if action == "rating_sync":
        return library.sync_rating(body)
    return library.rate(body)
