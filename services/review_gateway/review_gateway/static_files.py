"""The page's static files, read once at start and served under a version that names their bytes (PHONE-CORE 2.1).

A request is answered from this closed table only: a request path is never joined to the filesystem. This is string
substitution in the server, not a build; development, tests and production use the same code.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"
#: Only these are published under ``/s/<version>/``.
MEDIA_TYPES = {
    ".js": "text/javascript",
    ".css": "text/css",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webmanifest": "application/manifest+json",
}
TEMPLATE = "index.html"
#: PHONE-CORE 2.3: each is served at its own fixed address only, never under ``/s/<version>/``.
MANIFEST = "manifest.webmanifest"
WORKER = "sw.js"
VERSION_MARK = "{{V}}"
FEATURES_MARK = "{{FEATURES}}"
STYLES_MARK = "{{STYLES}}"
#: The ``order`` a feature's entry gives itself (``features/<id>/feature.js``).
_ORDER = re.compile(rb"^\s*order:\s*(\d+),", re.MULTILINE)


@dataclass(frozen=True)
class StaticFile:
    body: bytes
    media_type: str
    sha256: str


@dataclass(frozen=True)
class StaticSite:
    #: 12 hex digits that change exactly when a byte of the page's files changes.
    version: str
    #: Published path ("core/main.js") to file.
    files: Mapping[str, StaticFile]
    #: ``index.html`` with the version, the features and their stylesheets written into it.
    index: bytes
    #: The web app manifest with the version written into its icon addresses; empty when there is none.
    manifest: bytes
    #: ``sw.js`` as written; the server puts the version and the commit in front of it. Empty when there is none.
    worker: bytes

    def shell_digests(self) -> dict[str, str]:
        """What the service worker stores besides the versioned files, by address, to check it against."""

        pages = {"/": self.index, f"/{MANIFEST}": self.manifest}
        return {path: hashlib.sha256(body).hexdigest() for path, body in pages.items()}


def feature_ids(files: Mapping[str, StaticFile]) -> list[str]:
    """The features that have an entry, by their own ``order``: it orders their slots and their stylesheets."""

    found = []
    for name, file in files.items():
        parts = name.split("/")
        if len(parts) == 3 and parts[0] == "features" and parts[2] == "feature.js":
            order = _ORDER.search(file.body)
            found.append((int(order[1]) if order else 0, parts[1]))
    return [feature for _order, feature in sorted(found)]


def load_static(root: Path = STATIC_DIR) -> StaticSite:
    files = {}
    fixed = {}
    for path in root.rglob("*"):
        media_type = MEDIA_TYPES.get(path.suffix)
        if media_type is None or path.is_symlink() or not path.is_file():
            continue
        body = path.read_bytes()
        name = path.relative_to(root).as_posix()
        if name in (MANIFEST, WORKER):
            fixed[name] = body
            continue
        files[name] = StaticFile(body, media_type, hashlib.sha256(body).hexdigest())
    template = (root / TEMPLATE).read_bytes()
    named = {name: file.sha256 for name, file in files.items()}
    for name, body in {TEMPLATE: template, **fixed}.items():
        named[name] = hashlib.sha256(body).hexdigest()
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
    )
    manifest = fixed.get(MANIFEST, b"").replace(VERSION_MARK.encode(), version.encode())
    return StaticSite(version, files, index, manifest, fixed.get(WORKER, b""))
