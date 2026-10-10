"""Deterministic, bounded, redacted operator report over the observational inventory (PR-IMG-MODELS-152).

A pure function of an ``ObservationScan`` (plus optional, separately sourced runtime state and recorded outcomes): same
inputs, same JSON. It is point-in-time evidence for an operator, not durable truth and not a model manager. By default it
carries no absolute path, no prompt text and no raw metadata (only the few short declared labels the evidence modules keep);
absolute paths are included only when the caller asks. Every list is capped and the whole document has a size ceiling, with
explicit ``omitted`` counts so a reader can tell a truncated report from a complete one.

Nothing here selects, admits, installs, hashes or contacts anything. Readiness is reported as separate dimensions; the
words ``ready`` and ``qualified`` are never produced from file evidence.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, replace
from typing import Any

from src.assets.bundles import (
    NOT_CHECKED,
    ModelBundleEvidence,
    build_bundles,
    display,
)
from src.assets.observation import (
    FORMAT_UNINSPECTED,
    ObservationRoot,
    ObservationScan,
    ObservedFile,
)

REPORT_CONTRACT = "asset_topology_report/1"
MAX_LIST_ITEMS = 200
MAX_FILE_ROWS = 500
MAX_REPORT_BYTES = 2 * 1024 * 1024
NOT_WORKING_SEGMENT = "not working"

ProfileLookup = Callable[[str], bool]


def _cap(items: Sequence[Any], limit: int = MAX_LIST_ITEMS) -> dict[str, Any]:
    return {"items": list(items[:limit]), "omitted": max(0, len(items) - limit)}


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _is_not_working(primary: str) -> bool:
    return any(part.casefold() == NOT_WORKING_SEGMENT for part in primary.split("/")[:-1])


# --------------------------------------------------------------------------------------------------- file rows


def _file_row(item: ObservedFile, include_paths: bool) -> dict[str, Any]:
    header = item.header
    component = header.component if header else None
    row: dict[str, Any] = {
        "location": display(item),
        "kind": item.kind,
        "size_bytes": item.size,
        "format": header.format if header else None,
        "role": component.role if component else None,
        "architecture": component.architecture if component else None,
        "checkpoint_architecture": header.checkpoint_architecture if header else None,
        "variant": header.checkpoint_variant if header else None,
        "tensor_count": header.tensor_count if header else None,
        "identity": item.identity.status,
        "package": item.package_id,
        "errors": list(item.errors) + ([header.error] if header and header.error else []),
    }
    if header and header.gguf is not None:
        row["gguf"] = {
            "parsed": header.gguf.parsed,
            "architecture": header.gguf.architecture,
            "declared_file_type": header.gguf.quantization,
            "version": header.gguf.version,
        }
    if header and header.lora is not None:
        row["lora"] = {
            "style": header.lora.style,
            "tensor_family": header.lora.tensor_family,
            "declared": dict(header.lora.claimed_families),
            "conflicts": list(header.lora.conflicts),
            "suspected_misplaced_as": header.lora.suspected_misplaced_as,
            "declared_klein": header.lora.declared_klein,
        }
    if header and header.embedding is not None:
        row["embedding"] = {
            "kind": header.embedding.kind,
            "suitability": header.embedding.suitability,
            "vectors": header.embedding.vector_count,
        }
    if include_paths:
        row["path"] = item.path
    return row


def collisions(files: Sequence[ObservedFile]) -> list[dict[str, Any]]:
    """Same-kind files sharing a basename in different physical locations; never merged, never deduped by name."""

    groups: dict[tuple[str, str], list[ObservedFile]] = {}
    for item in files:
        groups.setdefault((item.kind, item.name.casefold()), []).append(item)
    found: list[dict[str, Any]] = []
    for (kind, name), items in sorted(groups.items()):
        if len(items) < 2:
            continue
        sizes = {item.size for item in items}
        verified = [item.identity.sha256 for item in items if item.identity.status == "verified"]
        if len(sizes) > 1 or len(set(verified)) > 1:
            equality = "different"  # different lengths or two different verified digests prove different bytes
        elif len(verified) == len(items):
            equality = "identical"  # every location carries the same verified SHA-256
        else:
            equality = "unverified"  # equal name and size never imply equal bytes
        found.append(
            {
                "name": name,
                "kind": kind,
                "byte_equality": equality,
                "locations": [
                    {
                        "location": display(item),
                        "size_bytes": item.size,
                        "identity": item.identity.status,
                    }
                    for item in sorted(items, key=display)
                ],
            }
        )
    return found


# --------------------------------------------------------------------------------------------------- runtime


def apply_runtime_state(
    bundles: Sequence[ModelBundleEvidence], scan: ObservationScan, state: Mapping[str, Any] | None
) -> tuple[ModelBundleEvidence, ...]:
    """Fill the served/selected dimensions from an explicitly requested, read-only Forge state (or leave ``not_checked``).

    ``state`` shape (built by ``image_backends.model_inventory_reconcile``): ``status`` (observed | unverified_runtime),
    ``checkpoint_listing`` (observed | unavailable), ``served_files`` (file paths | None), ``selection`` (observed |
    unavailable) and ``selected_file`` (a served file path, or None when the selection names no served file).
    """

    if not state:
        return tuple(bundles)
    by_display = {display(item): item for item in scan.files}
    result: list[ModelBundleEvidence] = []
    for bundle in bundles:
        readiness = dict(bundle.readiness)
        if state.get("status") != "observed":
            readiness["served_in_forge"] = readiness["selected_in_forge"] = "unverified_runtime"
        else:
            keys = {
                _path_key(by_display[name].path) for name in bundle.members if name in by_display
            }
            served = state.get("served_files")
            selected = state.get("selected_file")
            readiness["served_in_forge"] = (
                "unavailable"
                if state.get("checkpoint_listing") == "unavailable" or served is None
                else "served"
                if keys & {_path_key(path) for path in served}
                else "not_served"
            )
            readiness["selected_in_forge"] = (
                "unavailable"
                if state.get("selection") == "unavailable"
                else "selected"
                if selected and _path_key(selected) in keys
                else "not_selected"
            )
        result.append(replace(bundle, readiness=readiness))
    return tuple(result)


def runtime_section(state: Mapping[str, Any] | None) -> dict[str, Any]:
    if not state:
        return {"status": "not_requested", "note": "default report is fully offline"}
    section: dict[str, Any] = {
        "status": state.get("status"),
        "runtime_identity": state.get("runtime_identity"),
        "attribution": "this endpoint only; no managed-Forge qualification is attributed to it",
        "checkpoint_listing": state.get("checkpoint_listing"),
        "module_catalog": state.get("module_catalog"),
        "selected_modules": state.get("selected_modules"),
    }
    modules = state.get("module_names")
    section["module_names"] = None if modules is None else _cap(sorted(modules))
    return section


# --------------------------------------------------------------------------------------------------- qualification


def _recorded_match(
    bundle: ModelBundleEvidence,
    scan_files: Mapping[str, ObservedFile],
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """A recorded measured outcome applies to one exact candidate; structure alone never transfers a verdict."""

    primary = next((scan_files[name] for name in bundle.members if name in scan_files), None)
    if primary is None:
        return None
    for record in records:
        target = record.get("applies_to", {})
        structural = (
            bundle.architecture == target.get("architecture")
            and bundle.facts.get("hidden_size") == target.get("hidden_size")
            and bundle.quantization.get("precision_layout") == target.get("precision_layout")
            and bundle.quantization.get("dominant_dtype_by_bytes")
            == target.get("dominant_dtype_by_bytes")
        )
        if not structural:
            continue
        same_name_size = primary.name.casefold() == str(
            target.get("file_name", "")
        ).casefold() and primary.size == target.get("size_bytes")
        digest = primary.identity.sha256 if primary.identity.status == "verified" else None
        prefix, suffix = target.get("sha256_prefix"), target.get("sha256_suffix")
        if digest and prefix and suffix and digest.startswith(prefix) and digest.endswith(suffix):
            basis = "sha256_prefix_suffix_match"
        elif digest and prefix and suffix:
            return {
                "record": record["id"],
                "applies": False,
                "reason": "verified bytes differ from the evaluated candidate",
            }
        elif same_name_size:
            basis = "name_and_size_match_bytes_unverified"
        else:
            return {
                "record": record["id"],
                "applies": False,
                "reason": "same structural class as the evaluated candidate but a different file; the verdict is not transferred and this file is unevaluated",
            }
        return {
            "record": record["id"],
            "applies": True,
            "verdict": record["verdict"],
            "match_basis": basis,
            "scope": record.get("scope"),
        }
    return None


# --------------------------------------------------------------------------------------------------- backlog


def _category(bundle: ModelBundleEvidence) -> tuple[int, str] | None:
    layout = bundle.quantization.get("precision_layout")
    if bundle.architecture == "z_image_dit":
        return 1, "z_image"
    if (
        bundle.architecture == "flux2_dit"
        and bundle.packaging == "native"
        and layout in ("mixed_scaled", "unknown", "mixed_float")
    ):
        return 2, "flux2_quantized_native"
    if bundle.packaging == "gguf":
        return 3, "gguf_candidate"
    if (
        bundle.architecture == "sdxl_inpaint"
        or bundle.variant == "turbo"
        or bundle.architecture in ("sd1", "sd2", "sdxl_refiner")
    ):
        return 4, "sdxl_family_special"
    if bundle.architecture == "qwen_image_dit":
        return 5, "qwen_image"
    if bundle.architecture == "flux2_dit" and bundle.packaging == "native":
        return 6, "flux2_full_precision_native"
    if bundle.packaging == "diffusers_sharded":
        return 7, "diffusers_sharded_package"
    return None


def _next_diagnostic(
    bundle: ModelBundleEvidence, category: str, recorded: Mapping[str, Any] | None
) -> tuple[str, str]:
    """``(next_step, basis)``: the smallest justified read-only follow-up; hypotheses are labelled as such."""

    if category == "z_image":
        return (
            "Read-only: confirm the pinned Forge revision loads this Z-Image layout and quantization, then pair the "
            "header-possible encoder and AE; exactly one physical qualification only with new owner approval.",
            "header-derived requirements; loader support is unverified",
        )
    if category == "flux2_quantized_native":
        return (
            "Read-only: identify the numerical format (scale tensors plus quantized weights) against the pinned Forge "
            "loader and decide which encoder variant (plain or quantized) is intended; then a resource gate.",
            "dtype histogram and scale keys; loader support is unverified",
        )
    if category == "gguf_candidate":
        return (
            "Pinned Forge GGUF loader proof first, then full-stack memory feasibility; file size is not a memory footprint.",
            "container parsed only; content unverified",
        )
    if category == "flux2_full_precision_native":
        if recorded and recorded.get("applies"):
            return (
                f"Recorded outcome {recorded['verdict']} for this exact candidate ({recorded['record']}); candidate-specific, not retried.",
                "recorded measured outcome",
            )
        return (
            "Same structure as an evaluated full-precision candidate, but this file was not itself evaluated; treat as "
            "unqualified and evaluate read-only before any attempt.",
            "structural class only",
        )
    if category == "qwen_image":
        return (
            "Locate the Qwen2.5-VL text encoder the header requires; Qwen3 encoders are incompatible. Then evaluate "
            "combined memory; no substitution.",
            "header-derived requirement; documented encoder family",
        )
    if category == "diffusers_sharded_package":
        return (
            "Complete logical package, not a Forge-native single file; no automatically equivalent served model exists.",
            "shard manifest validation",
        )
    if bundle.architecture == "sdxl_inpaint":
        return (
            "9-channel SDXL inpainting UNet: it expects an image-plus-mask workflow; verify the workflow used before "
            "suspecting the file (hypothesis).",
            "tensor shape establishes the variant; the workflow cause is a hypothesis",
        )
    if bundle.variant == "turbo":
        return (
            "Metadata-declared SDXL Turbo: such models are normally run with very few steps and CFG near 1; compare "
            "StableNew's step/CFG/sampler settings (hypothesis).",
            "embedded metadata establishes the subtype; settings are a hypothesis",
        )
    if bundle.architecture in ("sd1", "sd2"):
        return (
            "SD1.x/2.x architecture: check that resolution, refiner, VAE and prompt settings are not SDXL-specific (hypothesis).",
            "tensor shape establishes the architecture; the cause is a hypothesis",
        )
    return (
        "No structural cause identified; collect the runtime log for this exact selection (read-only).",
        "no structural finding",
    )


def _bundle_dict(bundle: ModelBundleEvidence, full: bool) -> dict[str, Any]:
    data = asdict(bundle)
    for relationship in data["relationships"]:
        candidates = relationship["candidates"]
        kept = (
            [item for item in candidates if item["outcome"] != "incompatible"]
            if not full
            else candidates
        )
        relationship["candidates"] = kept
        relationship["incompatible_candidates_omitted"] = len(candidates) - len(kept)
    data["members"] = _cap(data["members"], 50)
    return data


def _summarize_adapters(files: Sequence[ObservedFile]) -> dict[str, Any]:
    loras = [item for item in files if item.header and item.header.lora is not None]
    embeddings = [item for item in files if item.header and item.header.embedding is not None]
    families = Counter(
        (item.header.lora.tensor_family or "unestablished")
        for item in loras
        if item.header and item.header.lora
    )
    styles = Counter(item.header.lora.style for item in loras if item.header and item.header.lora)
    return {
        "lora_count": len(loras),
        "lora_tensor_family": dict(sorted(families.items())),
        "lora_style": dict(sorted(styles.items())),
        "lora_conflicts": _cap(
            [
                {"location": display(item), "conflicts": list(item.header.lora.conflicts)}
                for item in loras
                if item.header and item.header.lora and item.header.lora.conflicts
            ]
        ),
        "suspected_misplaced": _cap(
            [
                {
                    "location": display(item),
                    "kind": item.kind,
                    "observed_as": item.header.lora.suspected_misplaced_as,
                }
                for item in loras
                if item.header and item.header.lora and item.header.lora.suspected_misplaced_as
            ]
        ),
        "lora_declared_klein": _cap(
            [
                {"location": display(item), "declared": item.header.lora.declared_klein}
                for item in loras
                if item.header and item.header.lora and item.header.lora.declared_klein
            ]
        ),
        "embedding_count": len(embeddings),
        "embedding_suitability": dict(
            sorted(
                Counter(
                    item.header.embedding.suitability
                    for item in embeddings
                    if item.header and item.header.embedding
                ).items()
            )
        ),
        "embedding_note": "suitability is stated only from a positive tensor signature; nothing is ever inserted into a prompt",
    }


def build_report(
    scan: ObservationScan,
    *,
    include_paths: bool = False,
    roots: Sequence[ObservationRoot] = (),
    runtime_state: Mapping[str, Any] | None = None,
    recorded_outcomes: Sequence[Mapping[str, Any]] = (),
    profile_lookup: ProfileLookup | None = None,
    limits: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The whole report as a JSON-serializable dict. Deterministic for equal inputs; no clock, no environment."""

    files_by_display = {display(item): item for item in scan.files}
    bundles = apply_runtime_state(build_bundles(scan), scan, runtime_state)
    root_paths = {root.label: str(root.path) for root in roots}

    # exact-profile *name* match is the only profile signal; bytes, runtime and hardware are not verified here
    def with_profile(bundle: ModelBundleEvidence) -> ModelBundleEvidence:
        readiness = dict(bundle.readiness)
        name = bundle.primary.rsplit("/", 1)[-1]
        if profile_lookup is not None and bundle.packaging in ("native", "bundled_checkpoint"):
            readiness["exact_profile_admitted"] = (
                "profile_name_match_unverified" if profile_lookup(name) else "none"
            )
        return replace(bundle, readiness=readiness)

    bundles = tuple(with_profile(bundle) for bundle in bundles)
    recorded_for: dict[str, dict[str, Any] | None] = {
        bundle.bundle_id: _recorded_match(bundle, files_by_display, recorded_outcomes)
        for bundle in bundles
    }
    updated: list[ModelBundleEvidence] = []
    for bundle in bundles:
        readiness = dict(bundle.readiness)
        match = recorded_for[bundle.bundle_id]
        if match and match.get("applies"):
            readiness["hardware_qualified"] = f"recorded_{str(match['verdict']).lower()}"
        updated.append(replace(bundle, readiness=readiness))
    bundles = tuple(updated)

    kinds = Counter(item.kind for item in scan.files)
    formats = Counter((item.header.format if item.header else "unreadable") for item in scan.files)
    unrecognized = [
        display(item)
        for item in scan.files
        if item.header
        and item.header.format == "safetensors"
        and item.kind in ("checkpoint", "text_encoder", "transformer", "vae")
        and item.header.component
        and item.header.component.role == "unrecognized"
        and not item.header.error
    ]
    errors = [
        {
            "location": display(item),
            "errors": list(item.errors)
            + ([item.header.error] if item.header and item.header.error else []),
        }
        for item in scan.files
        if item.errors or (item.header and item.header.error)
    ]
    packages = [
        {
            "id": package.package_id,
            "status": package.status,
            "member_count": len(package.members),
            "expected_shards": len(package.expected_shards),
            "missing": list(package.missing),
            "extra": list(package.extra),
            "problems": list(package.problems),
            "declared_total_size": package.declared_total_size,
            "observed_total_size": package.observed_total_size,
            "config_association": package.config_association,
            "architecture": package.component.architecture if package.component else None,
        }
        for package in scan.packages
    ]

    categorised: list[tuple[int, str, ModelBundleEvidence]] = []
    for bundle in bundles:
        category = _category(bundle)
        if category is not None:
            categorised.append((category[0], category[1], bundle))
    categorised.sort(key=lambda row: (row[0], row[2].bundle_id.casefold()))

    def entry(rank: int, category: str, bundle: ModelBundleEvidence) -> dict[str, Any]:
        recorded = recorded_for[bundle.bundle_id]
        step, basis = _next_diagnostic(bundle, category, recorded)
        return {
            "rank": rank,
            "category": category,
            "bundle": bundle.bundle_id,
            "operator_status": "not_working_operator_provided"
            if _is_not_working(bundle.primary)
            else None,
            "evidence": {
                "architecture": bundle.architecture,
                "variant": bundle.variant,
                "variant_basis": bundle.variant_basis,
                "packaging": bundle.packaging,
                "precision_layout": bundle.quantization.get("precision_layout"),
                "dominant_dtype_by_tensor_count": bundle.quantization.get(
                    "dominant_dtype_by_tensor_count"
                ),
                "dominant_dtype_by_bytes": bundle.quantization.get("dominant_dtype_by_bytes"),
                "dependencies_feasible": bundle.readiness["dependencies_feasible"],
                "identity": bundle.identity,
            },
            "recorded_outcome": recorded,
            "next_diagnostic": step,
            "diagnostic_basis": basis,
        }

    not_working = [
        entry(*(_category(bundle) or (8, "ordinary_sdxl")), bundle)
        for bundle in bundles
        if _is_not_working(bundle.primary)
    ]
    not_working.sort(key=lambda row: row["bundle"].casefold())
    priority = [entry(rank, category, bundle) for rank, category, bundle in categorised]

    report: dict[str, Any] = {
        "contract": REPORT_CONTRACT,
        "redaction": "absolute_paths_included" if include_paths else "labels_only",
        "point_in_time": "derived evidence about the files seen during this scan, not durable truth",
        "completeness": {
            "complete": scan.complete,
            "truncated_by": scan.truncated,
            "cancelled": scan.cancelled,
            "limits": dict(limits or {}),
            "note": None if scan.complete else "absence in this report is not evidence of absence",
        },
        "roots": [
            {
                "label": root.label,
                "kind": root.kind,
                "scanned": root.scanned,
                "reason": root.reason,
                "file_count": root.file_count,
                **(
                    {"path": root_paths[root.label]}
                    if include_paths and root.label in root_paths
                    else {}
                ),
            }
            for root in scan.roots
        ],
        "counts": {
            "observed_files": len(scan.files),
            "by_kind": dict(sorted(kinds.items())),
            "by_format": dict(sorted(formats.items())),
            "logical_packages": len(scan.packages),
            "shard_files_in_packages": sum(
                len(package.members) for package in scan.packages if package.index_file
            ),
            "model_bundles": len(bundles),
            "identity_verified": sum(
                1 for item in scan.files if item.identity.status == "verified"
            ),
            "identity_pending": sum(1 for item in scan.files if item.identity.status != "verified"),
            "distinct_embedding_names": len(
                {item.name.casefold() for item in scan.files if item.kind == "embedding"}
            ),
            "format_uninspected": sum(
                1 for item in scan.files if item.header and item.header.format == FORMAT_UNINSPECTED
            ),
        },
        "identity_note": "pending means no fingerprint-validated SHA-256 exists in the registry cache; no hash was computed",
        "unrecognized": _cap(sorted(unrecognized)),
        "collisions": _cap(collisions(scan.files)),
        "path_aliases": _cap(
            [
                {"location": display(item), "aliases": list(item.aliases)}
                for item in scan.files
                if item.aliases
            ]
        ),
        "skipped": _cap([{"location": name, "reason": reason} for name, reason in scan.skipped]),
        "unassociated_configs": _cap(
            [
                {"root": label, "directory": directory, "reason": reason}
                for label, directory, reason in scan.unassociated_configs
            ]
        ),
        "packages": _cap(packages),
        "adapters": _summarize_adapters(scan.files),
        "bundles": _cap([_bundle_dict(bundle, False) for bundle in bundles]),
        "not_working_cases": _cap(not_working),
        "priority_candidates": _cap(priority),
        "runtime": runtime_section(runtime_state),
        "errors": _cap(errors),
        "readiness_dimensions_note": (
            f"{NOT_CHECKED} means nothing was checked; no dimension here is ever 'ready' or 'qualified' from file evidence"
        ),
        "files": _cap([_file_row(item, include_paths) for item in scan.files], MAX_FILE_ROWS),
    }
    return _enforce_ceiling(report)


def _enforce_ceiling(report: dict[str, Any]) -> dict[str, Any]:
    """Keep the serialized report under ``MAX_REPORT_BYTES`` by dropping the bulkiest detail first, saying so."""

    dropped: list[str] = []
    for key in ("files", "bundles", "priority_candidates"):
        if len(json.dumps(report, sort_keys=True, default=str)) <= MAX_REPORT_BYTES:
            break
        report[key] = {"items": [], "omitted": report[key]["omitted"] + len(report[key]["items"])}
        dropped.append(key)
    report["size_ceiling"] = {"max_bytes": MAX_REPORT_BYTES, "sections_dropped": dropped}
    return report


def render_json(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str) + "\n"


def render_console(report: Mapping[str, Any]) -> str:
    """A compact human summary of the same report (never more evidence than the JSON)."""

    counts = report["counts"]
    lines = [
        f"Asset topology ({report['contract']}, {report['redaction']})",
        f"  complete scan: {report['completeness']['complete']}"
        + (
            f" (stopped: {report['completeness']['truncated_by']})"
            if report["completeness"]["truncated_by"]
            else ""
        ),
        f"  files {counts['observed_files']} | bundles {counts['model_bundles']} | packages {counts['logical_packages']} "
        f"| identity verified {counts['identity_verified']} / pending {counts['identity_pending']}",
        "  roots: "
        + ", ".join(
            f"{root['label']}={root['file_count'] if root['scanned'] else 'not scanned'}"
            for root in report["roots"]
        ),
        f"  collisions: {len(report['collisions']['items'])} | suspected misplaced: "
        f"{len(report['adapters']['suspected_misplaced']['items'])}",
        "Not Working cases:",
    ]
    for row in report["not_working_cases"]["items"]:
        lines.append(
            f"  - {row['bundle']}: {row['evidence']['architecture']} -> {row['next_diagnostic']}"
        )
    lines.append("Priority candidates:")
    for row in report["priority_candidates"]["items"]:
        lines.append(
            f"  {row['rank']}. [{row['category']}] {row['bundle']}: {row['next_diagnostic']}"
        )
    return "\n".join(lines) + "\n"


__all__ = [
    "MAX_REPORT_BYTES",
    "REPORT_CONTRACT",
    "apply_runtime_state",
    "build_report",
    "collisions",
    "render_console",
    "render_json",
    "runtime_section",
]
