"""Worker-only readiness for selected runtime checkpoints, using AssetRegistry."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.learning.variable_selection_contract import resource_entry_internal

if TYPE_CHECKING:
    from src.assets import AssetRecord, AssetRegistry
    from src.assets.registry import CheckpointInspection
    from src.image_backends.model_policy import ModelPolicy
    from src.pipeline.compile_evidence import CompileEvidence


def _model_label(model: str, index: int, show_names: bool) -> str:
    # Runtime identities can include paths; diagnostics never include local paths.
    name = model.replace("\\", "/").rsplit("/", 1)[-1].replace("\n", " ").replace("\r", " ")
    return f"Model {index}: {name}" if show_names else f"Model {index}"


def _require_supported_record(
    model: str, record: AssetRecord | CheckpointInspection, label: str
) -> ModelPolicy:
    """Explain unusable family evidence precisely, then let the canonical ``ModelPolicy`` decide eligibility.

    The branches below only diagnose *why* a header/sidecar yields no resolved family (conflict, unreadable, refiner or
    inpaint, nothing recognizable) so the operator gets actionable guidance. Whether a resolved family may take part
    in a study is not decided here: the policy resolved from this very evidence is asked through
    ``candidate_ineligibility`` and nothing else.
    """
    from src.assets.compatibility import (
        CompatibilityStatus,
        EvidenceConfidence,
        embedded_metadata_field_present,
        sidecar_metadata_field_present,
    )
    from src.image_backends.model_policy import resolve_model_policy
    from src.learning.model_comparison import candidate_ineligibility

    profile = record.compatibility
    assert profile is not None
    if profile.status is CompatibilityStatus.CONFLICTING:
        reason = "conflicting family metadata/structural evidence; correct the conflicting evidence or select another checkpoint"
    elif profile.structural_error:
        reason = f"unreadable checkpoint metadata/structure: {profile.structural_error}; verify a complete supported local checkpoint"
    elif profile.checkpoint_architecture in ("sdxl_refiner", "sdxl_inpaint"):
        reason = f"{profile.checkpoint_architecture} is not an SDXL base txt2img envelope; select a standard SDXL base checkpoint"
    elif profile.status is not CompatibilityStatus.RESOLVED or not any(
        item.confidence in (EvidenceConfidence.METADATA, EvidenceConfidence.STRUCTURAL)
        for item in profile.evidence
    ):
        if record.embedded_metadata_error or any(loc.sidecar_error for loc in record.locations):
            reason = "unreadable checkpoint metadata; repair supported embedded/sidecar metadata"
        elif embedded_metadata_field_present(record.embedded_metadata) or any(
            sidecar_metadata_field_present(loc.sidecar_metadata) for loc in record.locations
        ):
            reason = "unclassified family metadata and unrecognized structure; supply authoritative supported base-model metadata or select a supported SDXL base checkpoint"
        else:
            reason = "family metadata missing and structure unrecognized; select a supported safetensors SDXL base checkpoint or supply authoritative metadata"
    else:
        # A resolved family: the policy it resolves to (from this evidence alone) says whether a study may use it.
        policy = resolve_model_policy(model, family_lookup=lambda _name: profile)
        reason = candidate_ineligibility(policy)
        if reason is None:
            return policy
        reason += "; select a registry-evidenced model with an explicit capability policy or an exact qualified profile"
    raise ValueError(f"{label}: {reason}; rebuild Preview")


def _selection_path(
    model: str, entries: Sequence[Any], index: int, *, show_names: bool = True
) -> tuple[Path, dict[str, Any]]:
    from src.image_backends.model_policy import _model_key

    label = _model_label(model, index, show_names)

    matches = [entry for entry in entries if resource_entry_internal(entry) == model]
    if len(matches) != 1:
        raise ValueError(
            f"{label}: ambiguous or outdated runtime identity; refresh model resources and reselect"
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
                f"{label}: runtime checkpoint path is not absolute; expose an authoritative accessible local filename"
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
                f"{label}: runtime name and checkpoint filename disagree; refresh WebUI model resources"
            )
        if not path.is_file():
            raise ValueError(
                f"{label}: served checkpoint is unavailable locally; check the WebUI model location/access or use a locally accessible checkpoint"
            )
        return path.resolve(), raw
    # A familiar basename under the configured root is not proof that WebUI
    # serves that file. Filesystem discovery already supplies its exact path.
    raise ValueError(
        f"{label}: exact served checkpoint filename is missing; refresh model resources, verify the WebUI root, and expose an accessible authoritative filename"
    )


def prepare_comparison_evidence(
    models: Sequence[str],
    resources: Sequence[Any],
    *,
    registry: AssetRegistry | None = None,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[str], None] | None = None,
    show_names: bool = True,
) -> CompileEvidence:
    """Explicit Preview trigger: fingerprint selected files, hash only stale ones.

    No WebUI/network calls, full scans, runtime changes, or family guesses.
    First-time hashing reads all bytes of selected files; cancellation is checked
    every registry chunk. Returned CompileEvidence is one pinned cache context.

    A selection whose canonical ``ModelPolicy`` is an exact qualified profile has that profile as its identity
    authority: its checkpoint is neither fingerprinted, inspected nor hashed here. Every other selection is admitted only
    when the policy resolved from its own header/sidecar evidence is eligible (``candidate_ineligibility``).
    """
    from src.assets import AssetKind, AssetRegistry
    from src.image_backends.forge_klein_lora import RegistryLoraResolver
    from src.image_backends.model_policy import RegistryFamilyLookup, resolve_model_policy
    from src.learning.model_comparison import candidate_ineligibility, candidate_models
    from src.pipeline.compile_evidence import CompileEvidence

    models = candidate_models(models)
    registry = registry or AssetRegistry()
    paths, catalog = {}, {}
    for index, model in enumerate(models, 1):
        paths[model], catalog[model] = _selection_path(
            model, resources, index, show_names=show_names
        )
    # The canonical policy for an exact profile is a whole-name match that needs no registry evidence.
    exact_authority = {model for model in models if resolve_model_policy(model).exact_identity_authority}
    stale = [
        paths[model]
        for model in models
        if model not in exact_authority and not registry.checkpoint_is_current(paths[model])
    ]
    # Inspect only selected stale headers before paying for byte identity. Warm
    # evidence is pinned below without any header read or redundant hashing.
    for index, model in enumerate(models, 1):
        if paths[model] in stale:
            if cancelled and cancelled():
                raise InterruptedError("Checkpoint evidence refresh cancelled")
            label = _model_label(model, index, show_names)
            if progress:
                progress(f"{label}: checking safetensors header and metadata")
            try:
                inspection = registry.inspect_checkpoint(paths[model])
            except OSError:
                raise ValueError(
                    f"{label}: checkpoint header unavailable; verify local file access and retry Preview"
                ) from None
            _require_supported_record(model, inspection, label)
    if stale:
        if progress:
            progress(
                "Reading selected checkpoint bytes for SHA-256 evidence; first use may take several minutes"
            )

        def reading(path: Path, read_bytes: int, total: int) -> None:
            if progress:
                index = next(i for i, model in enumerate(models, 1) if paths[model] == path)
                model = models[index - 1]
                progress(
                    f"{_model_label(model, index, show_names)}: SHA-256 identity {read_bytes * 100 // max(1, total)}%"
                )

        try:
            refreshed = registry.refresh(checkpoint_paths=stale, cancelled=cancelled, progress=reading)
            if progress:
                cost = refreshed.counters
                progress(
                    f"Checkpoint evidence ready: {cost.hashes_computed} byte identity computed, "
                    f"{cost.hash_cache_hits} reused ({cost.header_reads} header and {cost.sidecar_reads} sidecar "
                    f"refresh, {cost.hash_seconds:.1f}s hashing)"
                )
        except OSError as exc:
            if isinstance(exc, (InterruptedError, TimeoutError)):
                raise
            failed_index = next(
                (i for i, model in enumerate(models, 1) if str(paths[model]) == str(exc.filename)),
                None,
            )
            label = (
                _model_label(models[failed_index - 1], failed_index, show_names)
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
        label = _model_label(model, index, show_names)
        policy = evidence.policy_for(model)
        if policy.exact_identity_authority:
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
                f"{label}: checkpoint evidence missing; retry Preview to refresh the selected file"
            )
        record = records[0]
        # WebUI's legacy `hash` field is not a SHA-256 prefix. Only its explicit
        # sha256 field can corroborate the registry's content identity.
        expected = str(catalog[model].get("sha256") or "").lower()
        if expected and (len(expected) < 8 or not record.sha256.startswith(expected)):
            raise ValueError(
                f"{label}: WebUI hash disagrees with local checkpoint; refresh WebUI resources and verify the served file"
            )
        _require_supported_record(model, record, label)
        ineligible = candidate_ineligibility(policy)
        if ineligible is not None or policy.evidence != "registry_evidence":
            raise ValueError(f"{label}: canonical target policy is unverified; rebuild Preview")
        assert record.compatibility is not None
        provenance = [
            {"source": item.source, "confidence": item.confidence.value}
            for item in record.compatibility.evidence
            if item.confidence.value != "filename_hint"
        ]
        identities[model] = {
            "authority": "asset_registry",
            "sha256": record.sha256,
            "family_evidence": provenance,
            "checkpoint_structure": dict(record.structural_evidence),
        }
        if progress:
            sources = ", ".join(dict.fromkeys(item["source"] for item in provenance))
            progress(f"{label}: ready; {policy.family.upper()} evidence from {sources}")
    evidence.model_identities = identities
    return evidence
