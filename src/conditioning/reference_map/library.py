"""Publishing a prepared map into the existing OpenPose conditioning-image library (PR-IMG-CNET-230).

The map is written under ``<WebUI root>/models/OpenPose/created/`` with a content-derived name
(``<modality>-<first 16 hex of the map SHA-256>.png``), so saving the same map twice is idempotent and two different maps
never share a name. The write is atomic and never overwrites a file: bytes go to a temporary file in the same folder and
are published with a hard link (which fails if the name exists), falling back to an exists-checked rename where links are
unavailable; a name taken by anything else moves on to ``-2``, ``-3``... The library identity returned is the plain
library-relative path a ``controlnet-unit.v1`` ``asset`` stores. The destination folder must be a real directory inside
the resolved library (a symlink or junction is refused), and the published file is read back through the library's own
bounded reader before it is reported. An adjacent bounded, sanitized provenance sidecar records how the map was made
(no absolute path, source bytes, landmarks or prompt). Blocking: call from a worker.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.conditioning.openpose import normalize_asset_identity
from src.conditioning.openpose_library import (
    OpenPoseInputError,
    library_root,
    read_bounded_file,
    read_library_image,
    validate_image_bytes,
)
from src.conditioning.reference_map.contracts import (
    CODE_NOT_PREPARED,
    LIBRARY_CODE_PREFIX,
    MAX_PROVENANCE_BYTES,
    PROVENANCE_CONTRACT,
    PreparedMap,
    ReferenceMapError,
)
from src.conditioning.reference_map.source import reverify_source

CREATED_FOLDER = "created"
SIDECAR_SUFFIX = ".stablenew-map.json"
MAX_NAME_ATTEMPTS = 50


def _refuse(code: str, message: str) -> ReferenceMapError:
    return ReferenceMapError(LIBRARY_CODE_PREFIX + code, message)


@dataclass(frozen=True, slots=True)
class SavedMap:
    #: Library-relative POSIX identity, exactly what a unit's ``asset`` stores.
    identity: str
    sha256: str
    size: int
    width: int
    height: int
    #: ``False`` when the image was saved but its provenance sidecar could not be written.
    provenance_saved: bool
    #: ``True`` when an identical map already existed under this name and was reused.
    reused: bool = False


def is_link(path: Path) -> bool:
    """A symlink or a Windows junction (both can redirect a path outside the library)."""

    if path.is_symlink():
        return True
    isjunction = getattr(os.path, "isjunction", None)
    return bool(isjunction is not None and isjunction(path))


def contained_folder(root: Path, name: str = CREATED_FOLDER) -> Path:
    """The ``name`` folder under the resolved library root, created if absent, refused if it is a link or escapes."""

    root_resolved = root.resolve(strict=True)
    folder = root_resolved / name
    try:
        if is_link(folder):
            raise _refuse(
                "escape", "The library folder for created maps is a link and was refused."
            )
        folder.mkdir(exist_ok=True)
        resolved = folder.resolve(strict=True)
    except OSError as exc:
        raise _refuse(
            "write_failed", "The library folder for created maps cannot be used."
        ) from exc
    if resolved.parent != root_resolved or not resolved.is_dir() or resolved.name != name:
        raise _refuse("escape", "The library folder for created maps resolves outside the library.")
    return resolved


def provenance_document(prepared: PreparedMap) -> dict[str, Any]:
    """The sanitized, deterministic sidecar content: hashes, dimensions and method identity only."""

    source = prepared.source
    return {
        "contract": PROVENANCE_CONTRACT,
        "modality": prepared.modality,
        "method": {
            "id": prepared.method.method_id,
            "version": prepared.method.version,
            "config": prepared.method.config,
        },
        "source": {
            "file_sha256": source.file_sha256,
            "file_size": source.file_size,
            "format": source.image_format,
            "width": source.width,
            "height": source.height,
            "oriented_sha256": source.oriented_sha256,
            "exif_transposed": source.exif_transposed,
        },
        "result": {
            "sha256": prepared.sha256,
            "width": prepared.width,
            "height": prepared.height,
            "bytes": len(prepared.png),
        },
        "auxiliary": {
            "resource": prepared.auxiliary_resource,
            "files": [
                {
                    "role": item.role,
                    "path": item.relative,
                    "sha256": item.sha256,
                    "size_bytes": item.size_bytes,
                    "pinned": item.pinned,
                }
                for item in prepared.auxiliary
            ],
        },
        "runtime": dict(sorted(prepared.runtime.items())),
        "warnings": list(prepared.warnings),
    }


def provenance_bytes(prepared: PreparedMap) -> bytes:
    data = json.dumps(
        provenance_document(prepared), sort_keys=True, ensure_ascii=True, indent=1
    ).encode("ascii")
    if len(data) > MAX_PROVENANCE_BYTES:
        raise _refuse("provenance_oversized", "The provenance record is too large to store.")
    return data + b"\n"


def read_provenance(webui_root: Path | str | None, identity: str) -> dict[str, Any] | None:
    """The sidecar of a library map, or ``None`` when it is absent, oversized, corrupt or off-contract (never raises)."""

    try:
        root = library_root(webui_root)
        if root is None:
            return None
        image = (root.resolve(strict=True) / normalize_asset_identity(identity)).resolve(
            strict=True
        )
        sidecar = image.with_name(image.stem + SIDECAR_SUFFIX)
        if is_link(sidecar) or not sidecar.is_file():
            return None
        with sidecar.open("rb") as stream:
            data = stream.read(MAX_PROVENANCE_BYTES + 1)
        if len(data) > MAX_PROVENANCE_BYTES:
            return None
        document = json.loads(data.decode("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict) or document.get("contract") != PROVENANCE_CONTRACT:
        return None
    return document


def _publish(temporary: Path, destination: Path) -> None:
    """Make ``temporary`` appear at ``destination`` without ever replacing an existing file (raises FileExistsError)."""

    try:
        os.link(temporary, destination)
        return
    except FileExistsError:
        raise
    except OSError:
        pass  # hard links unavailable on this volume: fall back to an exists-checked rename
    if destination.exists() or is_link(destination):
        raise FileExistsError(destination.name)
    os.rename(temporary, destination)


def _write_temporary(folder: Path, data: bytes, suffix: str) -> Path:
    descriptor, name = tempfile.mkstemp(dir=folder, prefix=".stablenew-", suffix=suffix)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _same_bytes(path: Path, data: bytes) -> bool:
    try:
        return not is_link(path) and read_bounded_file(path) == data
    except OpenPoseInputError:
        return False


def save_map(prepared: PreparedMap, webui_root: Path | str | None) -> SavedMap:
    """Publish the prepared map and its provenance; returns the library identity. Raises ``ReferenceMapError``."""

    if prepared.source_path is None:
        raise ReferenceMapError(CODE_NOT_PREPARED, "The map was not prepared from a source image.")
    reverify_source(prepared.source_path, prepared.source.file_sha256)
    if hashlib.sha256(prepared.png).hexdigest() != prepared.sha256:
        raise _refuse("corrupt", "The prepared map no longer matches its recorded hash.")
    try:
        validate_image_bytes(prepared.png)
    except OpenPoseInputError as exc:
        raise _refuse(exc.code, str(exc)) from exc
    root = library_root(webui_root)
    if root is None:
        raise _refuse(
            "no_library",
            "Configure the Stable Diffusion WebUI root to save maps into its OpenPose library.",
        )
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise _refuse("no_library", "The OpenPose library folder cannot be created.") from exc
    folder = contained_folder(root)
    provenance = provenance_bytes(prepared)
    base = f"{prepared.modality}-{prepared.sha256[:16]}"
    for attempt in range(MAX_NAME_ATTEMPTS):
        name = f"{base}.png" if attempt == 0 else f"{base}-{attempt + 1}.png"
        destination = folder / name
        reused = False
        if destination.exists() or is_link(destination):
            if not _same_bytes(destination, prepared.png):
                continue  # a different file owns this name; never touch it
            reused = True
        else:
            temporary: Path | None = None
            try:
                temporary = _write_temporary(folder, prepared.png, ".part")
                _publish(temporary, destination)
            except FileExistsError:
                continue  # lost a race for the name; it is someone else's file now
            except OSError as exc:
                raise _refuse(
                    "write_failed", "The map could not be written to the library."
                ) from exc
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        identity = f"{CREATED_FOLDER}/{name}"
        try:
            _, verified = read_library_image(root, identity)
        except OpenPoseInputError as exc:
            if not reused:
                destination.unlink(missing_ok=True)
            raise _refuse(exc.code, str(exc)) from exc
        if verified.sha256 != prepared.sha256:
            if not reused:
                destination.unlink(missing_ok=True)
            raise _refuse("corrupt", "The saved map did not read back identically and was removed.")
        saved_sidecar = _write_sidecar(folder, destination, provenance)
        return SavedMap(
            identity=normalize_asset_identity(identity),
            sha256=prepared.sha256,
            size=verified.size,
            width=verified.width,
            height=verified.height,
            provenance_saved=saved_sidecar,
            reused=reused,
        )
    raise _refuse("name_collision", "No free name was available for the map in the library.")


def _write_sidecar(folder: Path, image: Path, data: bytes) -> bool:
    target = folder / (image.stem + SIDECAR_SUFFIX)
    temporary: Path | None = None
    try:
        if is_link(target):
            return False
        temporary = _write_temporary(folder, data, ".part")
        os.replace(temporary, target)
        temporary = None
        return True
    except OSError:
        return False
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


__all__ = [
    "CREATED_FOLDER",
    "SIDECAR_SUFFIX",
    "SavedMap",
    "contained_folder",
    "is_link",
    "provenance_bytes",
    "provenance_document",
    "read_provenance",
    "save_map",
]
