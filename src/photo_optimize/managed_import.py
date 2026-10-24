"""Operator-confirmed import of existing image files into the managed Photo Optimize workspace (PR-GUI-UX-580).

Two steps, both run on a worker: ``plan_managed_import`` only reads (existence, supported type, decodable geometry,
SHA-256, and any managed asset already holding the same bytes) and ``apply_managed_import`` runs only after the operator
confirmed the plan. The copy itself is the store's existing ``import_photo``; originals are never modified, renamed or
deleted. Identity is the exact file content: a matching filename alone never makes two photos "the same".

Nothing here reads or copies Review state: a selection that came from History carries no lineage into the managed
asset. The new asset's baseline comes from the caller's ``baseline_defaults`` (Photo Optimize's own current
authority), exactly as for Import Photos.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .results import digest
from .settings import decoded_geometry

SUPPORTED_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})

NEW = "new"
EXISTING = "existing"
REFUSED = "refused"

OPEN_EXISTING = "open_existing"
IMPORT_COPY = "import_copy"


@dataclass(frozen=True)
class ImportRow:
    path: str
    status: str
    sha256: str = ""
    size: int = 0
    mtime_ns: int = 0
    existing_asset_ids: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class ManagedImportPlan:
    rows: tuple[ImportRow, ...]

    def with_status(self, status: str) -> list[ImportRow]:
        return [row for row in self.rows if row.status == status]

    @property
    def importable(self) -> bool:
        return any(row.status in {NEW, EXISTING} for row in self.rows)

    def describe(self) -> str:
        """Plain text for the confirmation; file names only, never prompt text."""

        lines = [f"{len(self.rows)} image(s) from Review:"]
        for row in self.rows:
            name = Path(row.path).name
            if row.status == NEW:
                lines.append(f"  NEW        {name}: will be copied into the managed workspace")
            elif row.status == EXISTING:
                lines.append(
                    f"  MANAGED    {name}: identical bytes are already managed as "
                    f"{', '.join(row.existing_asset_ids)}"
                )
            else:
                lines.append(f"  REFUSED    {name}: {row.reason}")
        lines.append("")
        lines.append(
            "Matching uses the exact file content (SHA-256), never the file name. "
            "Originals are never changed or deleted; nothing is queued."
        )
        return "\n".join(lines)


def plan_managed_import(store: Any, paths: Sequence[str | Path]) -> ManagedImportPlan:
    """Read-only preflight of ``paths`` (in order); never creates, copies or writes anything."""

    rows: list[ImportRow] = []
    seen_in_selection: dict[str, str] = {}
    for raw in paths:
        path = Path(raw)
        text = str(path)
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            rows.append(ImportRow(text, REFUSED, reason="Unsupported image type (PNG, JPEG or WebP only)."))
            continue
        try:
            stat = path.stat()
            if not path.is_file():
                raise FileNotFoundError(text)
            decoded_geometry(path)
            sha = digest(path)
        except FileNotFoundError:
            rows.append(ImportRow(text, REFUSED, reason="The file is missing."))
            continue
        except (OSError, ValueError) as exc:
            reason = getattr(exc, "strerror", None) or "The file cannot be read as an image."
            rows.append(ImportRow(text, REFUSED, reason=str(reason)))
            continue
        if sha in seen_in_selection:
            rows.append(
                ImportRow(
                    text,
                    REFUSED,
                    sha256=sha,
                    reason=f"Same bytes as {Path(seen_in_selection[sha]).name} earlier in this selection.",
                )
            )
            continue
        seen_in_selection[sha] = text
        existing = tuple(store.find_asset_ids_by_content(sha))
        rows.append(
            ImportRow(
                text,
                EXISTING if existing else NEW,
                sha256=sha,
                size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                existing_asset_ids=existing,
            )
        )
    return ManagedImportPlan(tuple(rows))


@dataclass
class ManagedImportResult:
    imported: list[tuple[str, str]] = field(default_factory=list)  # (source path, new asset id)
    opened_existing: list[tuple[str, str]] = field(default_factory=list)  # (source path, existing asset id)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (source path, reason)
    warnings: list[str] = field(default_factory=list)

    def asset_ids(self) -> list[str]:
        """Assets to select afterwards, in the operator's order."""

        return [asset_id for _path, asset_id in (*self.imported, *self.opened_existing)]

    def describe(self) -> str:
        lines = [
            f"Imported as new managed photos: {len(self.imported)}",
            f"Opened already-managed photos: {len(self.opened_existing)}",
            f"Failed or refused: {len(self.failed)}",
        ]
        lines.extend(f"  FAILED {Path(path).name}: {reason}" for path, reason in self.failed)
        lines.extend(f"  NOTE {warning}" for warning in self.warnings)
        lines.append("Original files were not changed.")
        return "\n".join(lines)


def apply_managed_import(
    store: Any,
    plan: ManagedImportPlan,
    *,
    baseline_defaults: dict[str, Any] | None,
    duplicates: str = OPEN_EXISTING,
) -> ManagedImportResult:
    """Import the planned rows the operator confirmed. A changed source is reported and skipped, never guessed."""

    result = ManagedImportResult()
    for row in plan.rows:
        if row.status == REFUSED:
            result.failed.append((row.path, row.reason))
            continue
        if row.status == EXISTING and duplicates == OPEN_EXISTING:
            result.opened_existing.append((row.path, row.existing_asset_ids[0]))
            continue
        try:
            if digest(row.path) != row.sha256:
                result.failed.append((row.path, "The file changed since you reviewed it; review again."))
                continue
            asset = store.import_photo(row.path, baseline_defaults=baseline_defaults)
        except (OSError, ValueError) as exc:
            reason = getattr(exc, "strerror", None) or str(exc) or type(exc).__name__
            result.failed.append((row.path, str(reason)))
            continue
        result.imported.append((row.path, asset.asset_id))
        if (asset.original_sha256 or "").lower() != row.sha256.lower():
            result.warnings.append(
                f"{Path(row.path).name} changed while it was copied; the managed copy holds the newer bytes."
            )
    return result


__all__ = [
    "EXISTING",
    "IMPORT_COPY",
    "NEW",
    "OPEN_EXISTING",
    "REFUSED",
    "ImportRow",
    "ManagedImportPlan",
    "ManagedImportResult",
    "apply_managed_import",
    "plan_managed_import",
]
