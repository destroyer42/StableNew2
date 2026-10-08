"""Worker-only readiness for selected runtime checkpoints, using AssetRegistry."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.learning.variable_selection_contract import resource_entry_internal

if TYPE_CHECKING:
    from src.assets import AssetRegistry
    from src.pipeline.compile_evidence import CompileEvidence


def _selection_path(model: str, entries: Sequence[Any], index: int) -> tuple[Path, dict[str, Any]]:
    from src.image_backends.model_policy import _model_key

    matches = [entry for entry in entries if resource_entry_internal(entry) == model]
    if len(matches) != 1:
        raise ValueError(
            f"Model {index}: ambiguous or outdated runtime identity; refresh model resources and reselect"
        )
    entry = matches[0]
    raw = (
        entry.get("raw", entry) if isinstance(entry, dict) else getattr(entry, "raw", None)
    ) or {}
    filename = raw.get("filename") or raw.get("path")
    if filename:
        path = Path(filename).expanduser()
        if not path.is_absolute():
            raise ValueError(
                f"Model {index}: runtime checkpoint path is not absolute; expose an authoritative accessible local filename"
            )
        title = str(raw.get("title") or "").replace("\\", "/")
        if title.endswith("]") and " [" in title:
            title = title[: title.rindex(" [")]
        title_path = Path(title)
        title_parts = title_path.parts
        # WebUI flattens a checkpoint's relative subdirectory into model_name.
        # Accept that documented resource shape only when title is an exact
        # suffix of the served file, rather than guessing from a display label.
        flattened = (
            str(title_path.with_suffix("")).replace("\\", "_").replace("/", "_")
            if title_path.name
            else ""
        )
        title_matches = bool(title_parts) and tuple(
            part.casefold() for part in path.parts[-len(title_parts) :]
        ) == tuple(part.casefold() for part in title_parts)
        if _model_key(path.name) != _model_key(model) and not (
            title_matches and model.casefold() == flattened.casefold()
        ):
            raise ValueError(
                f"Model {index}: runtime name and checkpoint filename disagree; refresh WebUI model resources"
            )
        if not path.is_file():
            raise ValueError(
                f"Model {index}: served checkpoint is unavailable locally; check the WebUI model location/access or use a locally accessible checkpoint"
            )
        return path.resolve(), raw
    # A familiar basename under the configured root is not proof that WebUI
    # serves that file. Filesystem discovery already supplies its exact path.
    raise ValueError(
        f"Model {index}: exact served checkpoint filename is missing; refresh model resources, verify the WebUI root, and expose an accessible authoritative filename"
    )


def prepare_comparison_evidence(
    models: Sequence[str],
    resources: Sequence[Any],
    *,
    registry: AssetRegistry | None = None,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[str], None] | None = None,
) -> CompileEvidence:
    """Explicit Preview trigger: fingerprint selected files, hash only stale ones.

    No WebUI/network calls, full scans, runtime changes, or family guesses.
    First-time hashing reads all bytes of selected files; cancellation is checked
    every registry chunk. Returned CompileEvidence is one pinned cache context.
    """
    from src.assets import AssetKind, AssetRegistry
    from src.assets.compatibility import (
        embedded_metadata_field_present,
        sidecar_metadata_field_present,
    )
    from src.image_backends.forge_klein_lora import RegistryLoraResolver
    from src.image_backends.forge_klein_profile import is_klein_transformer_name
    from src.image_backends.model_policy import RegistryFamilyLookup
    from src.learning.model_comparison import candidate_models
    from src.pipeline.compile_evidence import CompileEvidence

    models = candidate_models(models)
    registry = registry or AssetRegistry()
    paths, catalog = {}, {}
    for index, model in enumerate(models, 1):
        paths[model], catalog[model] = _selection_path(model, resources, index)
    stale = [
        paths[model]
        for model in models
        if not is_klein_transformer_name(model) and not registry.checkpoint_is_current(paths[model])
    ]
    if stale:
        if progress:
            progress(
                "Reading selected checkpoint bytes for SHA-256 evidence; first use may take several minutes"
            )

        def reading(path: Path, read_bytes: int, total: int) -> None:
            if progress:
                index = next(i for i, model in enumerate(models, 1) if paths[model] == path)
                progress(f"Model {index}: checkpoint evidence {read_bytes * 100 // max(1, total)}%")

        try:
            registry.refresh(checkpoint_paths=stale, cancelled=cancelled, progress=reading)
        except OSError as exc:
            if isinstance(exc, (InterruptedError, TimeoutError)):
                raise
            failed_index = next(
                (i for i, model in enumerate(models, 1) if str(paths[model]) == str(exc.filename)),
                None,
            )
            label = (
                f"Model {failed_index}"
                if failed_index is not None
                else "Selected checkpoint evidence"
            )
            raise ValueError(
                f"{label}: evidence read/cache unavailable; verify local file/cache access and retry Preview"
            ) from None
    if cancelled and cancelled():
        raise InterruptedError("Checkpoint evidence refresh cancelled")
    evidence = CompileEvidence(
        family_lookup=RegistryFamilyLookup(registry, model_paths=paths),
        lora_resolver=RegistryLoraResolver(registry, cache_only=True),
    )
    identities: dict[str, dict[str, Any]] = {}
    for index, model in enumerate(models, 1):
        policy = evidence.policy_for(model)
        if policy.qualified:
            identities[model] = {
                "authority": "exact_profile",
                "profile_ref": dict(policy.profile_ref or {}),
            }
            continue
        records = [
            record
            for record in registry.cached_snapshot().records_for(AssetKind.CHECKPOINT)
            if any(
                location.kind is AssetKind.CHECKPOINT and location.path == paths[model]
                for location in record.locations
            )
        ]
        if len(records) != 1:
            raise ValueError(
                f"Model {index}: checkpoint evidence missing; retry Preview to refresh the selected file"
            )
        record = records[0]
        # WebUI's legacy `hash` field is not a SHA-256 prefix. Only its explicit
        # sha256 field can corroborate the registry's content identity.
        expected = str(catalog[model].get("sha256") or "").lower()
        if expected and (len(expected) < 8 or not record.sha256.startswith(expected)):
            raise ValueError(
                f"Model {index}: WebUI hash disagrees with local checkpoint; refresh WebUI resources and verify the served file"
            )
        if policy.family != "sdxl" or policy.evidence != "registry_evidence":
            if policy.evidence == "conflicting_evidence":
                reason = (
                    "conflicting family metadata; correct conflicting embedded/sidecar metadata"
                )
            elif policy.evidence == "unknown_evidence":
                if record.embedded_metadata_error or any(
                    location.sidecar_error for location in record.locations
                ):
                    reason = (
                        "unreadable checkpoint metadata; repair supported embedded/sidecar metadata"
                    )
                elif embedded_metadata_field_present(record.embedded_metadata) or any(
                    sidecar_metadata_field_present(location.sidecar_metadata)
                    for location in record.locations
                ):
                    reason = "unclassified family metadata; supply authoritative supported base-model metadata"
                else:
                    reason = "family metadata missing; supply authoritative supported base-model metadata"
            else:
                reason = "family is not qualified for Model Comparison; select registry-evidenced SDXL or an exact qualified profile"
            raise ValueError(f"Model {index}: {reason}; rebuild Preview")
        identities[model] = {"authority": "asset_registry", "sha256": record.sha256}
    evidence.model_identities = identities
    return evidence
