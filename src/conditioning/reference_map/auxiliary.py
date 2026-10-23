"""Installed auxiliary-model identity for map preparation, taken from the curated catalog and the asset registry.

PR-ASSET-130 owns what the expected bytes are (``config/curated_asset_catalog.json``) and what is installed
(``AssetRegistry``, kind ``AUXILIARY_MODEL`` under ``models/StableNewAux``). This module only asks that readiness
projection a narrower question: may this resource be used right now? A required file with a pinned digest must be
byte-verified; a file the catalog cannot pin (a small configuration JSON) is accepted and its digest recorded with a
warning. Before inference the verified files are copied into a private staging directory while being hashed again, so
the bytes the model sees are the bytes that were verified (no swap between check and use). No network, no download.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.assets.resource_catalog import (
    ROOT_AUXILIARY,
    ROOT_LABELS,
    Catalog,
    CatalogError,
    load_catalog,
)
from src.assets.resource_readiness import (
    AMBIGUOUS,
    MISMATCH,
    MISSING,
    PRESENT_UNVERIFIED,
    VERIFIED,
    build_report,
    collect_installed_evidence,
)
from src.conditioning.reference_map.contracts import (
    CODE_CANCELLED,
    AuxiliaryFileIdentity,
    ProviderUnavailable,
    ReferenceMapError,
)

RESOURCE_BY_MODALITY: dict[str, str] = {
    "depth": "depth-anything-v2-small-hf",
    "openpose": "dwpose-onnx",
}
TITLE_BY_MODALITY: dict[str, str] = {
    "depth": "Depth Anything V2 Small",
    "openpose": "DWPose ONNX",
}
_COPY_CHUNK = 1024 * 1024
_ROOT_PREFIX = ROOT_LABELS[ROOT_AUXILIARY] + "/"


@dataclass(frozen=True, slots=True)
class VerifiedResource:
    resource_id: str
    files: tuple[AuxiliaryFileIdentity, ...]
    warnings: tuple[str, ...] = ()

    def by_role(self) -> dict[str, AuxiliaryFileIdentity]:
        return {item.role: item for item in self.files}


def _unavailable(modality: str, reasons: tuple[str, ...]) -> ProviderUnavailable:
    return ProviderUnavailable(
        f"{TITLE_BY_MODALITY[modality]} is not ready ({', '.join(reasons)}). Open Debug Hub, Model Resources "
        "for the exact files to obtain and where to place them; StableNew never downloads models.",
        reasons=reasons,
    )


def verify_resource(
    registry: Any,
    modality: str,
    *,
    catalog: Catalog | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> VerifiedResource:
    """Refresh the auxiliary root once and require the resource's files to be present and byte-verified.

    Raises ``ProviderUnavailable`` with precise reason codes, or ``ReferenceMapError(cancelled)``.
    """

    resource_id = RESOURCE_BY_MODALITY[modality]
    if getattr(registry, "webui_root", None) is None:
        raise _unavailable(modality, ("no_webui_root",))
    try:
        catalog = catalog or load_catalog()
    except CatalogError as exc:
        raise _unavailable(modality, ("catalog_unreadable",)) from exc
    evidence = collect_installed_evidence(
        registry, catalog, refresh=True, cancelled=cancelled, roots=frozenset({ROOT_AUXILIARY})
    )
    if not evidence.complete:
        if evidence.incomplete_reason == "cancelled":
            raise ReferenceMapError(CODE_CANCELLED, "Cancelled.")
        raise _unavailable(modality, (f"evidence_incomplete:{evidence.incomplete_reason}",))
    report = build_report(catalog, evidence)
    entry = next((item for item in report["resources"] if item["id"] == resource_id), None)
    if entry is None:
        raise _unavailable(modality, ("not_in_catalog",))
    declared = next((item for item in catalog.resources if item.id == resource_id), None)
    own_prefix = f"{_ROOT_PREFIX}{declared.placement_directory}/" if declared is not None else ""
    reasons: list[str] = []
    files: list[AuxiliaryFileIdentity] = []
    warnings: list[str] = []
    for item in entry["files"]:
        if not item["required"]:
            continue
        role, status = str(item["role"]), item["status"]
        pinnable = any(variant["sha256"] for variant in item["expected"])
        if status == VERIFIED or (status == PRESENT_UNVERIFIED and not pinnable):
            installed = item["installed"][0]
            location = str(installed["locations"][0])
            # Defense in depth: the readiness projection already matches inside the resource directory only.
            if not own_prefix or not location.startswith(own_prefix) or not installed["sha256"]:
                reasons.append(f"unusable:{role}")
                continue
            files.append(
                AuxiliaryFileIdentity(
                    role=role,
                    relative=location[len(_ROOT_PREFIX) :],
                    sha256=str(installed["sha256"]),
                    size_bytes=int(installed["size_bytes"]),
                    pinned=status == VERIFIED,
                )
            )
            if status != VERIFIED:
                warnings.append("auxiliary_config_unpinned")
        elif status == MISSING:
            reasons.append(f"resource_missing:{role}")
        elif status == MISMATCH:
            reasons.append(f"hash_mismatch:{role}")
        elif status == AMBIGUOUS:
            reasons.append(f"ambiguous:{role}")
        else:
            reasons.append(f"{status}:{role}")
    if reasons:
        raise _unavailable(modality, tuple(reasons))
    return VerifiedResource(resource_id, tuple(files), tuple(dict.fromkeys(warnings)))


def stage_resource(
    resource: VerifiedResource,
    webui_root: Path | str,
    destination: Path,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Path]:
    """Copy each verified file into ``destination`` (flat names), re-hashing it on the way.

    The directory the model loads from therefore contains exactly the verified files and nothing an operator left next
    to them. A file that no longer has its verified digest refuses the preparation before any inference starts.
    """

    root = (Path(str(webui_root)).expanduser() / "models" / "StableNewAux").resolve(strict=True)
    destination.mkdir(parents=True, exist_ok=True)
    staged: dict[str, Path] = {}
    for item in resource.files:
        source = (root / item.relative).resolve(strict=True)
        if not source.is_relative_to(root) or not source.is_file():
            raise ProviderUnavailable(
                "A model file resolves outside the auxiliary model folder and was refused.",
                reasons=(f"escape:{item.role}",),
            )
        target = destination / Path(item.relative).name
        digest = hashlib.sha256()
        with source.open("rb") as reader, target.open("wb") as writer:
            while chunk := reader.read(_COPY_CHUNK):
                if cancelled is not None and cancelled():
                    raise ReferenceMapError(CODE_CANCELLED, "Cancelled.")
                digest.update(chunk)
                writer.write(chunk)
        if digest.hexdigest() != item.sha256:
            shutil.rmtree(destination, ignore_errors=True)
            raise ProviderUnavailable(
                "A model file changed after it was verified; refresh Model Resources and try again.",
                reasons=(f"hash_mismatch:{item.role}",),
            )
        staged[item.role] = target
    return staged


__all__ = [
    "RESOURCE_BY_MODALITY",
    "TITLE_BY_MODALITY",
    "VerifiedResource",
    "stage_resource",
    "verify_resource",
]
