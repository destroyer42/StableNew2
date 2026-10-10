"""Read-only evidence gathering for one selected checkpoint (PR-IMG-MODELS-150).

The only I/O behind ``assess_model_readiness``: ``GET /sd-models`` (which local file Forge serves for the name), a bounded
safetensors header of that file, and - only when the header says the checkpoint needs separate components - ``GET
/sd-modules`` (the catalog) and ``GET /options`` (the live selection, via ``get_additional_modules``) plus a header read of
each catalog file. It never writes, hashes, loads a tensor, scans a directory or starts/stops anything. Any read that
fails is reported as unavailable, never as an empty list or a ready state.

Worker-side code: the Forge backend calls it before dispatch and the GUI calls it from an explicit, bounded background
check. It must never run on the Tk thread or at import.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from src.assets.component_evidence import ComponentEvidence, inspect_component_file
from src.image_backends.model_readiness import (
    CatalogModule,
    ModelReadiness,
    ReadinessStatus,
    assess_model_readiness,
)

logger = logging.getLogger(__name__)

#: ``filename -> evidence`` reader; ``None`` when the file cannot be stat-ed. The backend injects a fingerprint cache.
EvidenceReader = Callable[[str], "ComponentEvidence | None"]


def checkpoint_key(name: Any) -> str:
    """Name identity of a checkpoint title/model_name/file (no directory, no ``[hash]`` suffix, no extension)."""

    base = str(name or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    if base.endswith("]") and " [" in base:
        base = base[: base.rindex(" [")]
    lowered = base.strip().lower()
    for ext in (".safetensors", ".sft", ".ckpt", ".pt", ".pth"):
        if lowered.endswith(ext):
            return lowered[: -len(ext)]
    return lowered


def _default_reader(filename: str) -> ComponentEvidence | None:
    from pathlib import Path

    return inspect_component_file(filename) if Path(filename).exists() else None


def served_checkpoint_files(client: Any, model_name: str) -> set[str] | None:
    """Distinct local files Forge lists for ``model_name``; ``None`` when the listing cannot be read."""

    lister = getattr(client, "get_models", None)
    if not callable(lister):
        return None
    try:
        entries = lister()
    except Exception:  # noqa: BLE001 - an unreadable listing is absent evidence, never a guess
        return None
    if not isinstance(entries, list) or not entries:
        return None
    wanted = checkpoint_key(model_name)
    return {
        str(entry.get("filename") or "")
        for entry in entries
        if isinstance(entry, Mapping)
        and entry.get("filename")
        and wanted in {checkpoint_key(entry.get("title")), checkpoint_key(entry.get("model_name")), checkpoint_key(entry.get("filename"))}
    }


def probe_model_readiness(
    client: Any,
    model_name: str,
    *,
    evidence: EvidenceReader | None = None,
    profile_available: bool = False,
    profile_verified: bool = False,
) -> ModelReadiness:
    """One read-only readiness verdict for ``model_name`` against the endpoint behind ``client``."""

    name = str(model_name or "").strip()
    if profile_available:
        return assess_model_readiness(
            name, checkpoint=None, catalog=None, selected=None,
            profile_available=True, profile_verified=profile_verified,
        )
    read = evidence or _default_reader
    files = served_checkpoint_files(client, name) if name else None
    if not files:
        return assess_model_readiness(name, checkpoint=None, catalog=None, selected=None)
    if len(files) > 1:
        return ModelReadiness(
            name,
            ReadinessStatus.UNKNOWN_OR_CONFLICTING,
            "served_file_ambiguous",
            ("Forge lists more than one different file under this name, so the served checkpoint cannot be identified.",),
        )
    checkpoint = read(next(iter(files)))
    if checkpoint is None or checkpoint.error or not checkpoint.dependency_bearing:
        return assess_model_readiness(name, checkpoint=checkpoint, catalog=None, selected=None)

    catalog: list[CatalogModule] | None = None
    selected: list[str] | None = None
    try:
        # The tri-state catalog read: ``[]`` is an answer ("Forge lists nothing"), ``None`` a failed/blocked read. A client
        # without it can only offer the legacy list whose ``[]`` is ambiguous, so that is treated as unreadable.
        tri_state = getattr(client, "get_module_catalog", None)
        if callable(tri_state):
            modules = tri_state()
        else:
            legacy = getattr(client, "get_vae_models", None)
            modules = (legacy() or None) if callable(legacy) else None
        if isinstance(modules, list):
            catalog = []
            for item in modules:
                path = str(item.get("filename") or "") if isinstance(item, Mapping) else ""
                module = str(item.get("model_name") or "") if isinstance(item, Mapping) else ""
                if module:
                    catalog.append(CatalogModule(module, read(path) if path else None, bool(path)))
        reader = getattr(client, "get_additional_modules", None)
        observed = reader() if callable(reader) else None
        selected = list(observed) if isinstance(observed, list) else None
    except Exception:  # noqa: BLE001 - a failed read is "unavailable", reported as such
        logger.debug("Forge catalog/selection read failed while probing model readiness", exc_info=True)
    return assess_model_readiness(name, checkpoint=checkpoint, catalog=catalog, selected=selected)


__all__ = ["checkpoint_key", "probe_model_readiness", "served_checkpoint_files"]
