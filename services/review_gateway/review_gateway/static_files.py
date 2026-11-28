"""The page's static files, read once at start and served under a version that names their bytes (PHONE-CORE 2.1).

A request is answered from this closed table only: a request path is never joined to the filesystem. This is string
substitution in the server, not a build; development, tests and production use the same code.
"""

from __future__ import annotations

import hashlib
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


@dataclass(frozen=True)
class StaticFile:
    body: bytes
    media_type: str
    sha256: str


@dataclass(frozen=True)
class StaticSite:
    #: 12 hex digits that change exactly when a published byte or the template changes.
    version: str
    #: Published path ("core/main.js") to file.
    files: Mapping[str, StaticFile]
    #: ``index.html`` with the version written into it.
    index: bytes


def load_static(root: Path = STATIC_DIR) -> StaticSite:
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
    listing = "".join(f"{name}\0{digest}\n" for name, digest in sorted(named.items()))
    version = hashlib.sha256(listing.encode("utf-8")).hexdigest()[:12]
    return StaticSite(version, files, template.replace(VERSION_MARK.encode(), version.encode()))
