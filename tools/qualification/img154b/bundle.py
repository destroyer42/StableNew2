"""D7 (154B): the evidence bundle of one case: raw and redacted copies under the isolated, ignored evidence root.

Every file is created exclusively (an existing evidence file is never overwritten), written, flushed and fsynced, and listed
with its SHA-256 in ``index.json``. Raw copies keep the exact request, prompt and paths for the operator. Redacted copies
carry no raw prompt, personal profile path or hardware identifier and are the only form meant to leave the machine.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from tools.qualification.img154.evidence import REQUIRED_EVIDENCE_ITEMS, evidence_gaps, redact_value

BUNDLE_SCHEMA = "stablenew.img154b.evidence-bundle.v1"


class BundleError(OSError):
    """An evidence file could not be created without overwriting or losing something."""


class EvidenceBundle:
    def __init__(
        self, directory: str | os.PathLike[str], *, sync: Callable[[int], None] = os.fsync
    ) -> None:
        self.directory = Path(directory)
        self._sync = sync
        self._files: dict[str, dict[str, Any]] = {}
        self._items: dict[str, Any] = {}

    # ----------------------------------------------------------------------------------------------- writing
    def _write(self, relative: str, data: bytes) -> None:
        path = self.directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError as exc:
            raise BundleError(
                f"evidence file already exists and is never overwritten: {relative}"
            ) from exc
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            self._sync(stream.fileno())
        self._files[relative] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}

    def put_json(self, name: str, value: Any, *, item: str | None = None) -> None:
        """Raw and redacted JSON. ``item`` marks which required evidence item this file satisfies."""

        raw = json.dumps(value, indent=2, sort_keys=True, default=str).encode("utf-8")
        redacted = json.dumps(redact_value(value), indent=2, sort_keys=True, default=str).encode(
            "utf-8"
        )
        self._write(f"raw/{name}.json", raw)
        self._write(f"redacted/{name}.json", redacted)
        if item is not None:
            self._items[item] = f"redacted/{name}.json"

    def put_text(self, name: str, text: str, *, item: str | None = None) -> None:
        from tools.qualification.img154.evidence import redact_text

        self._write(f"raw/{name}.txt", text.encode("utf-8"))
        self._write(f"redacted/{name}.txt", redact_text(text).encode("utf-8"))
        if item is not None:
            self._items[item] = f"redacted/{name}.txt"

    def put_artifact(self, name: str, data: bytes) -> str:
        """A generated artifact (the output image): stored once, hashed, never redacted (it is the evidence itself)."""

        self._write(f"artifacts/{name}", data)
        return self._files[f"artifacts/{name}"]["sha256"]

    def note_item(self, item: str, reference: Any) -> None:
        self._items[item] = reference

    # ----------------------------------------------------------------------------------------------- summary
    def gaps(self) -> list[str]:
        return [finding.detail for finding in evidence_gaps(self._items)]

    def complete(self) -> bool:
        return not evidence_gaps(self._items)

    def finalize(self, *, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
        index = {
            "schema": BUNDLE_SCHEMA,
            "required_items": list(REQUIRED_EVIDENCE_ITEMS),
            "items": dict(self._items),
            "gaps": self.gaps(),
            "files": dict(sorted(self._files.items())),
            **(dict(extra) if extra else {}),
        }
        self._write(
            "index.json", json.dumps(index, indent=2, sort_keys=True, default=str).encode("utf-8")
        )
        return index
