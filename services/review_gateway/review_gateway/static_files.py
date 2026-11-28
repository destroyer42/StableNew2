"""The page's static files, read once at start and served under a version that names their bytes (PHONE-CORE 2.1).

A request is answered from this closed table only: a request path is never joined to the filesystem. This is string
substitution in the server, not a build; development, tests and production use the same code.
"""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"
#: Only these are published. ``index.html`` is a template and is served at ``/`` instead.
MEDIA_TYPES = {
    ".js": "text/javascript",
    ".css": "text/css",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webmanifest": "application/manifest+json",
}
TEMPLATE = "index.html"
VERSION_MARK = "{{V}}"
FEATURES_MARK = "{{FEATURES}}"
STYLES_MARK = "{{STYLES}}"
#: PHONE-CORE PS-1: the header's environment label ("Staging"); nothing on production, which sets none.
ENVIRONMENT_MARK = "{{ENVIRONMENT}}"
#: The ``order`` a feature's entry gives itself (``features/<id>/feature.js``).
_ORDER = re.compile(rb"^\s*order:\s*(\d+),", re.MULTILINE)


@dataclass(frozen=True)
class StaticFile:
    body: bytes
    media_type: str
    sha256: str


@dataclass(frozen=True)
class StaticSite:
    #: 12 hex digits that change exactly when a published byte, the template or the environment label changes.
    version: str
    #: Published path ("core/main.js") to file.
    files: Mapping[str, StaticFile]
    #: ``index.html`` with the version, the features and their stylesheets written into it.
    index: bytes


def feature_ids(files: Mapping[str, StaticFile]) -> list[str]:
    """The features that have an entry, by their own ``order``: it orders their slots and their stylesheets."""

    found = []
    for name, file in files.items():
        parts = name.split("/")
        if len(parts) == 3 and parts[0] == "features" and parts[2] == "feature.js":
            order = _ORDER.search(file.body)
            found.append((int(order[1]) if order else 0, parts[1]))
    return [feature for _order, feature in sorted(found)]


def load_static(root: Path = STATIC_DIR, *, environment_label: str = "") -> StaticSite:
    files = {}
    for path in root.rglob("*"):
        media_type = MEDIA_TYPES.get(path.suffix)
        if media_type is None or path.is_symlink() or not path.is_file():
            continue
        body = path.read_bytes()
        files[path.relative_to(root).as_posix()] = StaticFile(
            body, media_type, hashlib.sha256(body).hexdigest()
        )
    template = (root / TEMPLATE).read_bytes()
    named = {name: file.sha256 for name, file in files.items()}
    named[TEMPLATE] = hashlib.sha256(template).hexdigest()
    badge = ""
    if environment_label:
        badge = f'<span id="environment">{html.escape(environment_label)}</span>'
        named[ENVIRONMENT_MARK] = hashlib.sha256(badge.encode("utf-8")).hexdigest()
    listing = "".join(f"{name}\0{digest}\n" for name, digest in sorted(named.items()))
    version = hashlib.sha256(listing.encode("utf-8")).hexdigest()[:12]
    features = feature_ids(files)
    styles = "\n  ".join(
        f'<link rel="stylesheet" href="/s/{version}/features/{name}/{name}.css">'
        for name in features
        if f"features/{name}/{name}.css" in files
    )
    index = (
        template.replace(VERSION_MARK.encode(), version.encode())
        .replace(FEATURES_MARK.encode(), ",".join(features).encode())
        .replace(STYLES_MARK.encode(), styles.encode())
        .replace(ENVIRONMENT_MARK.encode(), badge.encode("utf-8"))
    )
    return StaticSite(version, files, index)
