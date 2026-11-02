"""Bounded structural scan of a binary FBX file (PR-VID-MOTION-354).

Answers "does this file hold a mesh, a skin, a skeleton, animation?" by reading the FBX node *headers* only: a record's
properties are never decoded except the first few short strings of ``Model`` / ``Deformer`` / ``Geometry`` objects, and a
record's children are never entered except under ``Objects``.  Nothing is imported, executed or rendered, so a file can be
classified without Blender and without trusting it.  Every read and every loop is bounded; a malformed or hostile file
produces ``FbxScan.error`` and never an exception.

Only binary FBX (``Kaydara FBX Binary``) is scanned; an ASCII FBX is reported as ``ascii`` with no content facts.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

BINARY_MAGIC = b"Kaydara FBX Binary  \x00\x1a\x00"
_HEADER_BYTES = len(BINARY_MAGIC) + 4
MAX_SCANNED_NODES = 400_000
MAX_PROPERTY_BYTES = 16 * 1024
MAX_BONE_NAMES = 512
MAX_NAME_CHARS = 120
_COUNTED = (
    "Geometry",
    "Model",
    "Deformer",
    "AnimationCurve",
    "AnimationCurveNode",
    "AnimationStack",
    "AnimationLayer",
    "NodeAttribute",
    "Material",
    "Pose",
)
_FIXED_SIZES = {b"Y": 2, b"C": 1, b"I": 4, b"F": 4, b"D": 8, b"L": 8}


@dataclass(frozen=True, slots=True)
class FbxScan:
    """What the node headers say.  ``error`` non-empty means nothing below is trustworthy."""

    encoding: str = "unknown"  # "binary" | "ascii" | "unknown"
    version: int = 0
    mesh_models: int = 0
    skeleton_bones: int = 0
    geometry_count: int = 0
    skin_deformers: int = 0
    cluster_deformers: int = 0
    animation_curves: int = 0
    animation_stacks: int = 0
    node_counts: dict[str, int] = field(default_factory=dict)
    bone_names: tuple[str, ...] = ()
    bone_names_truncated: bool = False
    error: str = ""

    @property
    def has_mesh(self) -> bool:
        return self.geometry_count > 0 and self.mesh_models > 0

    @property
    def has_skin(self) -> bool:
        return self.skin_deformers > 0 and self.cluster_deformers > 0

    @property
    def has_skeleton(self) -> bool:
        return self.skeleton_bones > 0

    @property
    def has_animation(self) -> bool:
        return self.animation_curves > 0 and self.animation_stacks > 0


class _Reader:
    """A bounds-checked view of one open file."""

    def __init__(self, handle: object, size: int, wide: bool) -> None:
        self.handle = handle
        self.size = size
        self.wide = wide
        self.header_bytes = 25 if wide else 13

    def read(self, offset: int, count: int) -> bytes:
        if offset < 0 or count < 0 or offset + count > self.size:
            raise ValueError("a record points outside the file")
        self.handle.seek(offset)  # type: ignore[attr-defined]
        data = self.handle.read(count)  # type: ignore[attr-defined]
        if len(data) != count:
            raise ValueError("the file ended inside a record")
        return bytes(data)

    def node_header(self, offset: int) -> tuple[int, int, int, str, int] | None:
        """``(end_offset, num_props, prop_len, name, props_offset)``; ``None`` for the null terminator."""

        raw = self.read(offset, self.header_bytes)
        if self.wide:
            end, num_props, prop_len, name_len = struct.unpack("<QQQB", raw)
        else:
            end, num_props, prop_len, name_len = struct.unpack("<IIIB", raw)
        if end == 0 and num_props == 0 and prop_len == 0 and name_len == 0:
            return None
        name = self.read(offset + self.header_bytes, name_len).decode("latin-1", "replace")
        props_offset = offset + self.header_bytes + name_len
        if end <= props_offset or end > self.size or props_offset + prop_len > end:
            raise ValueError("a record has an impossible length")
        return end, num_props, prop_len, name, props_offset


def _leading_strings(
    reader: _Reader, props_offset: int, prop_len: int, num_props: int
) -> list[str | int]:
    """Decode the first few properties when they are short ints or strings; stop at the first anything else."""

    if prop_len > MAX_PROPERTY_BYTES:
        return []
    data = reader.read(props_offset, prop_len)
    values: list[str | int] = []
    position = 0
    for _ in range(min(num_props, 4)):
        if position >= len(data):
            break
        code = data[position : position + 1]
        position += 1
        if code == b"L" and position + 8 <= len(data):
            values.append(struct.unpack_from("<q", data, position)[0])
            position += 8
        elif code in (b"S", b"R") and position + 4 <= len(data):
            (length,) = struct.unpack_from("<I", data, position)
            position += 4
            if length > len(data) - position:
                break
            if code == b"S":
                values.append(data[position : position + length].decode("utf-8", "replace"))
            position += length
        elif code in _FIXED_SIZES:
            position += _FIXED_SIZES[code]
        else:
            break  # an array or an unknown code: not needed
    return values


def _clean_name(raw: object) -> str:
    text = str(raw).split("\x00", 1)[0]
    return text[:MAX_NAME_CHARS]


def scan_fbx(path: str | Path) -> FbxScan:
    """Scan one FBX.  Never raises for file content."""

    try:
        target = Path(path)
        size = target.stat().st_size
        with target.open("rb") as handle:
            head = handle.read(_HEADER_BYTES)
            if head.startswith(b"; FBX") or head.lstrip().startswith(b"; FBX"):
                return FbxScan(encoding="ascii")
            if not head.startswith(BINARY_MAGIC) or len(head) < _HEADER_BYTES:
                return FbxScan(error="Not an FBX file (unrecognized header).")
            (version,) = struct.unpack_from("<I", head, len(BINARY_MAGIC))
            if not 6000 <= version <= 8000:
                return FbxScan(
                    encoding="binary", version=version, error=f"Unsupported FBX version {version}."
                )
            return _scan_binary(_Reader(handle, size, version >= 7500), version)
    except (OSError, ValueError, struct.error) as exc:
        return FbxScan(error=f"The FBX structure could not be read: {exc}")


def _scan_binary(reader: _Reader, version: int) -> FbxScan:
    counts: dict[str, int] = {}
    bones: list[str] = []
    mesh_models = skeleton_bones = skin = cluster = 0
    truncated = False
    scanned = 0
    offset = _HEADER_BYTES
    objects_span: tuple[int, int] | None = None
    while offset < reader.size - reader.header_bytes:
        header = reader.node_header(offset)
        if header is None:
            break
        end, _num, prop_len, name, props_offset = header
        scanned += 1
        if name == "Objects":
            objects_span = (props_offset + prop_len, end)
        offset = end
    if objects_span is None:
        return FbxScan(encoding="binary", version=version, error="The file has no Objects section.")

    child = objects_span[0]
    while child < objects_span[1] - reader.header_bytes + 1:
        header = reader.node_header(child)
        if header is None:
            break
        end, num_props, prop_len, name, props_offset = header
        scanned += 1
        if scanned > MAX_SCANNED_NODES:
            return FbxScan(
                encoding="binary", version=version, error="The file has too many records to scan."
            )
        if name in _COUNTED:
            counts[name] = counts.get(name, 0) + 1
        if name in ("Model", "Deformer", "Geometry"):
            strings = _leading_strings(reader, props_offset, prop_len, num_props)
            kind = str(strings[2]) if len(strings) >= 3 else ""
            if name == "Model":
                if kind == "Mesh":
                    mesh_models += 1
                elif kind == "LimbNode":
                    skeleton_bones += 1
                    if len(bones) < MAX_BONE_NAMES:
                        bones.append(_clean_name(strings[1]) if len(strings) > 1 else "")
                    else:
                        truncated = True
            elif name == "Deformer":
                if kind == "Skin":
                    skin += 1
                elif kind == "Cluster":
                    cluster += 1
        child = end
    return FbxScan(
        encoding="binary",
        version=version,
        mesh_models=mesh_models,
        skeleton_bones=skeleton_bones,
        geometry_count=counts.get("Geometry", 0),
        skin_deformers=skin,
        cluster_deformers=cluster,
        animation_curves=counts.get("AnimationCurve", 0),
        animation_stacks=counts.get("AnimationStack", 0),
        node_counts=counts,
        bone_names=tuple(bones),
        bone_names_truncated=truncated,
    )
