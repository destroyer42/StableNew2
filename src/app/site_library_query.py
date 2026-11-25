"""Validated query values shared by the Site library and its SQLite projection."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from math import gcd
from typing import Any

from src.app.site_media_files import SiteOutputError

PAGE_SIZE = 24
SEARCH_LIMIT = 100_000
SOURCES = frozenset(
    {"pipeline", "learning", "reprocess", "movie_clips", "svd", "video_eval", "other"}
)
SORTS = {
    "newest": "timestamp DESC, key",
    "oldest": "timestamp, key",
    "filename_asc": "name, key",
    "filename_desc": "name DESC, key",
}
FILTERS = {
    "source": "source",
    "model_family": "family",
    "model": "model",
    "workflow": "workflow",
    "aspect_ratio": "ratio",
    "orientation": "orientation",
}
TEXT_COLUMNS = {
    "name": ("name",),
    "tag": ("tags",),
    "prompt": ("prompt",),
    "model": ("model_text",),
    "seed": ("seed",),
    "all": ("name", "tags", "prompt", "model_text", "seed"),
}


def timestamp(value: object) -> int:
    """Return signed Unix microseconds, requiring an explicitly offset timestamp."""
    if not isinstance(value, str) or "T" not in value or not 20 <= len(value) <= 40:
        raise ValueError("Invalid timestamp")
    date = datetime.fromisoformat(value)
    if date.utcoffset() is None:
        raise ValueError("Missing timezone")
    delta = date.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def ratio_of(width: int, height: int) -> str | None:
    if not width or not height:
        return None
    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


@dataclass(frozen=True)
class LibraryQuery:
    kind: str
    sort: str
    field: str
    query: str
    filters: tuple[tuple[str, str | None], ...]
    dimensions: tuple[int, int] | None
    unknown_dimensions: bool
    after: int | None
    before: int | None
    offset: int
    revision: str
    refresh: bool

    @classmethod
    def parse(cls, body: dict[str, Any], *, legacy: bool = False) -> LibraryQuery:
        kind = body.get("kind", "all")
        sort = body.get("sort", "newest")
        field = body.get("field", "all")
        query = body.get("query", "")
        offset = body.get("offset", 0)
        revision = body.get("revision", "")
        refresh = body.get("refresh", False)
        filters = body.get("filters", {})
        if legacy:
            filters = {"source": body["source"]} if body.get("source", "") != "" else {}
        if (
            kind not in (("image", "video") if legacy else ("image", "video", "all"))
            or not isinstance(sort, str)
            or sort not in SORTS
            or not isinstance(field, str)
            or field not in TEXT_COLUMNS
            or (legacy and field == "model")
            or not isinstance(query, str)
            or len(query) > 240
            or type(offset) is not int
            or not 0 <= offset <= SEARCH_LIMIT
            or not isinstance(revision, str)
            or len(revision) > 64
            or type(refresh) is not bool
            or not isinstance(filters, dict)
            or filters.keys() - FILTERS.keys() - {"dimensions", "after", "before"}
        ):
            raise SiteOutputError("invalid_library_request")
        normalized: list[tuple[str, str | None]] = []
        for name in sorted(filters.keys() & FILTERS.keys()):
            value = filters[name]
            if value is None and name != "source":
                normalized.append((FILTERS[name], None))
                continue
            if not isinstance(value, str) or not value or len(value) > 240 or "\0" in value:
                raise SiteOutputError("invalid_library_request")
            if name == "source" and value not in SOURCES:
                raise SiteOutputError("invalid_library_request")
            if name == "orientation" and value not in ("portrait", "landscape", "square"):
                raise SiteOutputError("invalid_library_request")
            if name == "aspect_ratio":
                parts = value.split(":")
                if len(parts) != 2 or any(
                    not part.isascii() or not part.isdecimal() or len(part) > 6 for part in parts
                ):
                    raise SiteOutputError("invalid_library_request")
                value = ratio_of(*map(int, parts))
                if value is None:
                    raise SiteOutputError("invalid_library_request")
            normalized.append((FILTERS[name], value))
        dimensions = filters.get("dimensions")
        if dimensions is not None and (
            not isinstance(dimensions, list)
            or len(dimensions) != 2
            or any(type(value) is not int or not 1 <= value <= 65535 for value in dimensions)
        ):
            raise SiteOutputError("invalid_library_request")
        try:
            after = timestamp(filters["after"]) if "after" in filters else None
            before = timestamp(filters["before"]) if "before" in filters else None
            if after is not None and before is not None and after >= before:
                raise ValueError("Empty timestamp range")
        except (ValueError, OverflowError) as error:
            raise SiteOutputError("invalid_library_request") from error
        return cls(
            kind,
            sort,
            field,
            query.strip().casefold(),
            tuple(normalized),
            tuple(dimensions) if dimensions is not None else None,
            "dimensions" in filters and dimensions is None,
            after,
            before,
            offset,
            revision,
            refresh,
        )

    def identity(self) -> str:
        values = asdict(self)
        for key in ("offset", "revision", "refresh"):
            values.pop(key)
        return json.dumps(values, sort_keys=True)

    def where(self) -> tuple[str, list[object]]:
        clauses: list[str] = []
        values: list[object] = []

        def add(condition: str, *parameters: object) -> None:
            clauses.append(condition)
            values.extend(parameters)

        if self.kind != "all":
            add("kind = ?", self.kind)
        for column, value in self.filters:
            add(f"{column} IS ?", value)
        if self.dimensions is not None:
            add("width = ? AND height = ?", *self.dimensions)
        if self.unknown_dimensions:
            add("width IS NULL")
        if self.after is not None:
            add("timestamp >= ?", self.after)
        if self.before is not None:
            add("timestamp < ?", self.before)
        if self.query:
            fields = TEXT_COLUMNS[self.field]
            pieces = []
            for column in fields:
                if column == "seed":
                    seed = self.query
                    value = (
                        str(int(seed))
                        if seed.isascii() and seed.isdecimal() and len(seed) <= 20
                        else ""
                    )
                    pieces.append("seed = ?")
                    values.append(value or None)
                elif column == "tags":
                    pieces.append(
                        "EXISTS (SELECT 1 FROM json_each(tags) WHERE instr(value, ?) > 0)"
                    )
                    values.append(self.query)
                else:
                    pieces.append(f"instr({column}, ?) > 0")
                    values.append(self.query)
            clauses.append("(" + " OR ".join(pieces) + ")")
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), values
