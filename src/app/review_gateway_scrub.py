"""Take PC paths out of the metadata of an image that is about to be published (PHONE-FAST, RG-100 invariant 3).

StableNew embeds its generation record in every image, and parts of that record name files on the PC. A published
copy keeps the prompt and settings text and loses those paths. Pixels are never re-encoded: only the metadata
containers are rewritten. A field that is only a path is removed; a path inside longer text keeps its file name. The
PC's own file is never touched (callers pass bytes).
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import re
import struct
import zlib
from typing import Any

from PIL import Image

from src.utils.image_metadata import ImageMetadataContractV26, canonical_json_bytes

#: The directory part of an absolute Windows or UNC path, or of a user folder.
_PATH = re.compile(
    r"(?:\\\\\?\\)?"
    r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]+|\\\\[\w.$-]+\\|(?<![\w.:/])/(?:home|Users)/)"
    r"(?:[^\\/:*?\"<>|\r\n]*[\\/]+)*"
)
_PNG = b"\x89PNG\r\n\x1a\n"
_TEXT_CHUNKS = (b"tEXt", b"zTXt", b"iTXt")
_TEXT_LIMIT = 32 * 1024 * 1024
_EXIF_HEADER = b"Exif\x00\x00"
_USER_COMMENT = 37510
_SNMETA = b"SNMETA:"
_DROP = object()


class Unclean(Exception):
    """Metadata that may name a path and cannot be rewritten: the image must not be sent."""


def _scrub_value(value: Any) -> Any:
    if isinstance(value, str):
        if _PATH.match(value.strip()):
            return _DROP
        return _scrub_string(value)
    if isinstance(value, dict):
        kept = {}
        for name, inner in value.items():
            cleaned = _scrub_value(inner)
            if cleaned is not _DROP:
                kept[_PATH.sub("", str(name))] = cleaned
        return kept
    if isinstance(value, list):
        return [item for item in map(_scrub_value, value) if item is not _DROP]
    return value


def _scrub_string(text: str) -> str:
    """JSON held in a string is cleaned as JSON; other text loses the directories of any path in it."""

    if text.lstrip()[:1] in ("{", "["):
        try:
            parsed = json.loads(text)
        except (ValueError, RecursionError):
            pass
        else:
            cleaned = _scrub_value(parsed)
            if cleaned == parsed:
                return text
            return json.dumps(cleaned, ensure_ascii=False, sort_keys=True)
    return _PATH.sub("", text)


def _inflate(data: bytes) -> bytes:
    engine = zlib.decompressobj()
    result = engine.decompress(data, _TEXT_LIMIT)
    if engine.unconsumed_tail:
        raise Unclean("metadata too large")
    return result


def _decode_chunk(kind: bytes, data: bytes) -> tuple[str, str]:
    name, rest = data.split(b"\x00", 1)
    key = name.decode("latin-1")
    if kind == b"tEXt":
        return key, rest.decode("latin-1")
    if kind == b"zTXt":
        return key, _inflate(rest[1:]).decode("latin-1")
    compressed = rest[0] == 1
    _language, rest = rest[2:].split(b"\x00", 1)
    _translated, body = rest.split(b"\x00", 1)
    return key, (_inflate(body) if compressed else body).decode("utf-8", errors="replace")


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def _text_chunk(key: str, value: str) -> bytes:
    return _chunk(b"iTXt", key.encode("latin-1") + b"\x00\x00\x00\x00\x00" + value.encode("utf-8"))


def _clean_texts(texts: dict[str, str]) -> dict[str, str]:
    """The entries that change, by key. StableNew's payload keeps its own digest consistent."""

    contract = ImageMetadataContractV26
    changed: dict[str, str] = {}
    for key, value in texts.items():
        if key == contract.KEY_PAYLOAD_GZ_B64:
            raw = gzip.decompress(base64.b64decode(value))
            parsed = json.loads(raw)
            cleaned = _scrub_value(parsed)
            if cleaned != parsed:
                body = canonical_json_bytes(cleaned)
                changed[key] = base64.b64encode(gzip.compress(body, mtime=0)).decode("ascii")
                changed[contract.KEY_PAYLOAD_SHA256] = hashlib.sha256(body).hexdigest()
            continue
        cleaned_text = _scrub_string(value)
        if cleaned_text != value:
            changed[key] = cleaned_text
            if key == contract.KEY_PAYLOAD:
                changed[contract.KEY_PAYLOAD_SHA256] = hashlib.sha256(
                    cleaned_text.encode("utf-8")
                ).hexdigest()
    return changed


def _scrub_png(data: bytes) -> bytes:
    chunks: list[tuple[bytes, bytes, bytes]] = []  # (type, data, the whole chunk)
    position = len(_PNG)
    while position + 12 <= len(data):
        (length,) = struct.unpack(">I", data[position : position + 4])
        end = position + 12 + length
        if end > len(data):
            raise Unclean("truncated image")
        kind = data[position + 4 : position + 8]
        chunks.append((kind, data[position + 8 : end - 4], data[position:end]))
        position = end
    texts = dict(_decode_chunk(kind, body) for kind, body, _ in chunks if kind in _TEXT_CHUNKS)
    changed = _clean_texts(texts)
    out = [_PNG]
    dirty = False
    for kind, body, whole in chunks:
        if kind in _TEXT_CHUNKS:
            key, _value = _decode_chunk(kind, body)
            if key in changed:
                out.append(_text_chunk(key, changed[key]))
                dirty = True
                continue
        elif kind == b"eXIf":
            cleaned = _scrub_exif(_EXIF_HEADER + body)
            if cleaned is not None:
                out.append(_chunk(kind, cleaned[len(_EXIF_HEADER) :]))
                dirty = True
                continue
        out.append(whole)
    return b"".join(out) + data[position:] if dirty else data


def _scrub_exif(block: bytes) -> bytes | None:
    """A rewritten EXIF block (with its header), or ``None`` when it names no path."""

    exif = Image.Exif()
    exif.load(block)
    dirty = False
    entries = dict(exif)
    entries.update(exif.get_ifd(0x8769))  # the Exif sub-directory, where UserComment may live
    for tag, value in entries.items():
        raw = value if isinstance(value, bytes) else None
        text = value if isinstance(value, str) else None
        if raw is not None and raw.startswith(_SNMETA):
            parsed = json.loads(base64.b64decode(raw[len(_SNMETA) :]))
            changed = _clean_texts(parsed)  # the same keys a PNG holds as text chunks
            if changed:
                body = base64.b64encode(canonical_json_bytes({**parsed, **changed}))
                _set(exif, tag, _SNMETA + body)
                dirty = True
            continue
        if raw is not None:
            for encoding in ("utf-8", "utf-16-le", "utf-16-be"):
                if _PATH.search(raw.decode(encoding, errors="ignore")):
                    _delete(exif, tag)
                    dirty = True
                    break
            continue
        if text is not None and _PATH.search(text):
            _set(exif, tag, _scrub_string(text))
            dirty = True
    return exif.tobytes() if dirty else None


def _set(exif: Image.Exif, tag: int, value: Any) -> None:
    holder = exif if tag in exif else exif.get_ifd(0x8769)
    holder[tag] = value


def _delete(exif: Image.Exif, tag: int) -> None:
    holder = exif if tag in exif else exif.get_ifd(0x8769)
    del holder[tag]


def _scrub_jpeg(data: bytes) -> bytes:
    out = [data[:2]]
    position = 2
    dirty = False
    while position + 4 <= len(data) and data[position] == 0xFF and data[position + 1] != 0xDA:
        marker = data[position + 1]
        (length,) = struct.unpack(">H", data[position + 2 : position + 4])
        end = position + 2 + length
        body = data[position + 4 : end]
        segment = data[position:end]
        if marker == 0xE1 and body.startswith(_EXIF_HEADER):
            cleaned = _scrub_exif(body)
            if cleaned is not None:
                if len(cleaned) + 2 > 0xFFFF:
                    raise Unclean("metadata too large")
                segment = b"\xff\xe1" + struct.pack(">H", len(cleaned) + 2) + cleaned
                dirty = True
        elif marker in (0xE1, 0xFE) and _PATH.search(body.decode("utf-8", errors="ignore")):
            segment = b""  # XMP or a comment that names a path
            dirty = True
        out.append(segment)
        position = end
    return b"".join(out) + data[position:] if dirty else data


def _scrub_webp(data: bytes) -> bytes:
    out = []
    position = 12
    dirty = False
    while position + 8 <= len(data):
        kind = data[position : position + 4]
        (length,) = struct.unpack("<I", data[position + 4 : position + 8])
        end = position + 8 + length + (length & 1)
        body = data[position + 8 : position + 8 + length]
        piece = data[position:end]
        replacement: bytes | None = None
        if kind == b"EXIF":
            headed = body if body.startswith(_EXIF_HEADER) else _EXIF_HEADER + body
            cleaned = _scrub_exif(headed)
            if cleaned is not None:
                replacement = cleaned if body.startswith(_EXIF_HEADER) else cleaned[6:]
        elif kind == b"XMP " and _PATH.search(body.decode("utf-8", errors="ignore")):
            replacement = b" " * len(body)
        if replacement is not None:
            piece = kind + struct.pack("<I", len(replacement)) + replacement
            piece += b"\x00" * (len(replacement) & 1)
            dirty = True
        out.append(piece)
        position = end
    if not dirty:
        return data
    body = b"WEBP" + b"".join(out)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def scrub_image(data: bytes) -> bytes:
    """``data`` without PC paths in its metadata (the same object when there were none). Raises ``Unclean``."""

    try:
        if data.startswith(_PNG):
            return _scrub_png(data)
        if data.startswith(b"\xff\xd8"):
            return _scrub_jpeg(data)
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return _scrub_webp(data)
    except Unclean:
        raise
    except Exception as error:  # noqa: BLE001 - metadata that cannot be read cannot be shown to be clean
        raise Unclean("unreadable metadata") from error
    return data
