"""Offline readiness projection of installed assets against the curated catalog (PR-ASSET-130).

``build_report`` is a pure function of a ``Catalog`` and an ``InstalledEvidence``: same inputs, same bytes. It separates
three questions that file presence alone never answers: are the bytes the expected ones (integrity), is the whole group
there (dependency completeness) and can this product use them today (capability). A resource can therefore be
``verified`` on disk and still be ``needs_integration``.

``collect_installed_evidence`` is the only impure step. It reads the one ``AssetRegistry`` (an explicit streamed-SHA-256
refresh, or the stat-validated cached snapshot) and never loads a model, opens a pickle, starts a process, touches the
network or the queue. A report carries sanitized root labels and relative names only: no absolute path, no username.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from src.assets.resource_catalog import (
    ROOT_AUXILIARY,
    ROOT_CONTROLNET,
    ROOT_LABELS,
    Catalog,
    CatalogResource,
    ResourceFile,
)

REPORT_CONTRACT = "asset_readiness_report/1"
MAX_INSTALLED_FILES = 5_000

# Per-file and per-resource status vocabulary.
MISSING = "missing"
PRESENT_UNVERIFIED = "present_unverified"
VERIFIED = "verified"
MISMATCH = "mismatch"
AMBIGUOUS = "ambiguous"
UNSUPPORTED = "unsupported"
NEEDS_INTEGRATION = "needs_integration"
#: The evidence cannot answer (never refreshed, cancelled, refused, over a quota): never ``missing`` and never ``verified``.
INCOMPLETE = "incomplete"
STATUSES = (
    VERIFIED,
    PRESENT_UNVERIFIED,
    MISSING,
    MISMATCH,
    AMBIGUOUS,
    UNSUPPORTED,
    NEEDS_INTEGRATION,
    INCOMPLETE,
)

BASIS_REFRESH = "explicit_refresh"
BASIS_CACHE = "cached_snapshot"

#: Header evidence values (``controlnet_structure.STATUS_*``), repeated as plain text so the pure projection stays import-light.
_SDXL = "sdxl"
_NOT_SDXL = "not_sdxl"


@dataclass(frozen=True)
class InstalledFile:
    """One installed file as the registry knows it; ``relative`` is posix and below its root."""

    root: str
    relative: str
    size_bytes: int
    sha256: str | None
    header_error: str | None = None
    #: Header-derived ControlNet family evidence, collected only for files whose digest the catalog pins.
    controlnet_evidence: str | None = None

    @property
    def label(self) -> str:
        return f"{ROOT_LABELS[self.root]}/{self.relative}"


@dataclass(frozen=True)
class InstalledEvidence:
    files: tuple[InstalledFile, ...]
    basis: str
    #: False means absence is not evidence of absence (cached basis, cancellation, refusal, quota stop).
    complete: bool
    incomplete_reason: str | None = None
    refused_paths: int = 0


# --------------------------------------------------------------------------------------------------- projection


def _expected_relative(resource: CatalogResource, filename: str) -> str:
    return (
        f"{resource.placement_directory}/{filename}" if resource.placement_directory else filename
    )


def _name_match(resource: CatalogResource, spec: ResourceFile, item: InstalledFile) -> bool:
    if item.root != resource.placement_root:
        return False
    names = {variant.suggested_filename.casefold() for variant in spec.variants}
    if resource.placement_root == ROOT_AUXILIARY:
        return item.relative.casefold() in {_expected_relative(resource, name) for name in names}
    return item.relative.rsplit("/", 1)[-1].casefold() in names


def _identities(items: Sequence[InstalledFile]) -> list[dict[str, Any]]:
    grouped: dict[str, list[InstalledFile]] = {}
    for item in items:
        grouped.setdefault(item.sha256 or "", []).append(item)
    found = []
    for digest, members in grouped.items():
        found.append(
            {
                "sha256": digest or None,
                "size_bytes": members[0].size_bytes,
                "locations": sorted({item.label for item in members}),
            }
        )
    return sorted(found, key=lambda entry: (entry["sha256"] or "", entry["locations"]))


def _file_result(
    resource: CatalogResource, spec: ResourceFile, evidence: InstalledEvidence
) -> dict[str, Any]:
    pinned = spec.pinned_digests
    candidates = [
        item
        for item in evidence.files
        if item.root == resource.placement_root
        and (
            _name_match(resource, spec, item) or (item.sha256 is not None and item.sha256 in pinned)
        )
    ]
    reasons: list[str] = []
    digests = {item.sha256 for item in candidates}
    if not candidates:
        status = MISSING if evidence.complete else INCOMPLETE
        reasons.append("not_installed" if evidence.complete else "evidence_incomplete")
    elif len(digests) > 1:
        status = AMBIGUOUS
        reasons.append("multiple_distinct_contents")
    else:
        (digest,) = digests
        named = any(_name_match(resource, spec, item) for item in candidates)
        if digest is None:
            status = PRESENT_UNVERIFIED
            reasons.append("hash_not_computed")
        elif digest in pinned:
            status = VERIFIED
            if not named:
                reasons.append("verified_under_alias_name")
        elif spec.has_unpinned_variant or not pinned:
            status = PRESENT_UNVERIFIED
            reasons.append("no_pinned_hash")
        else:
            status = MISMATCH
            reasons.append("hash_mismatch")
        if any(item.header_error for item in candidates) and status in (
            VERIFIED,
            PRESENT_UNVERIFIED,
        ):
            status = PRESENT_UNVERIFIED
            reasons.append("header_unreadable")
        if status == VERIFIED and len({item.label for item in candidates}) > 1:
            reasons.append("duplicate_locations")
    return {
        "role": spec.role,
        "required": spec.required,
        "description": spec.description,
        "status": status,
        "reason_codes": sorted(set(reasons)),
        "expected": [
            {
                "upstream_path": variant.upstream_path,
                "suggested_filename": variant.suggested_filename,
                "sha256": variant.sha256,
                "size_bytes": variant.size_bytes,
                "hash_status": variant.hash_status,
            }
            for variant in spec.variants
        ],
        "installed": _identities(candidates),
        "_candidates": candidates,
    }


def _capability(resource: CatalogResource) -> dict[str, Any]:
    """What this product can use today, re-derived from product code; the catalog's claim alone never grants it."""

    declared = resource.capability
    policy = declared.policy
    reasons = list(declared.reason_codes)
    if declared.id.startswith("controlnet_unit."):
        from src.conditioning.controlnet import MODALITIES

        if declared.modality not in MODALITIES:
            policy = UNSUPPORTED
            reasons = ["modality_not_in_product_policy"]
    elif policy == "supported_now":
        policy = NEEDS_INTEGRATION  # only an existing, named product policy can make a catalog entry supported
        reasons = ["no_product_policy_for_capability"]
    return {
        "id": declared.id,
        "policy": policy,
        "modality": declared.modality,
        "reason_codes": sorted(set(reasons)),
        "basis": declared.basis,
    }


def _acquisition(resource: CatalogResource, files: list[dict[str, Any]]) -> dict[str, Any]:
    source = resource.source
    steps: list[str] = []
    revision = source.get("revision") if source.get("revision_status") == "pinned" else None
    where = f"{source['url']}" + (
        f" at revision {revision}" if revision else " (revision not pinned)"
    )
    for entry in files:
        if entry["status"] == VERIFIED:
            continue
        if entry["status"] in (MISMATCH, AMBIGUOUS):
            steps.append(
                f"Resolve {entry['role']}: the installed bytes are "
                f"{'not the expected ones' if entry['status'] == MISMATCH else 'ambiguous'}; "
                "remove or move the wrong copy yourself, then obtain the file again."
            )
        expected = entry["expected"]
        names = " or ".join(
            f"{item['upstream_path']} -> {item['suggested_filename']}" for item in expected
        )
        suffix = "" if entry["required"] else " (optional)"
        pending = any(item["sha256"] is None for item in expected)
        steps.append(
            f"Obtain {entry['role']}{suffix}: {names}."
            + (
                " No upstream SHA-256 was verified for it, so StableNew can only report it as present_unverified."
                if pending
                else ""
            )
        )
    if steps:
        steps.insert(
            0,
            f"Source: {where}. Download manually; StableNew does not download or install anything.",
        )
        steps.append(resource.placement_instructions)
    return {"url": source["url"], "revision": revision, "steps": steps}


def _headline(required: list[dict[str, Any]], capability: dict[str, Any]) -> tuple[str, list[str]]:
    statuses = {entry["status"] for entry in required}
    reasons: list[str] = []
    for status in (AMBIGUOUS, MISMATCH, MISSING, INCOMPLETE, PRESENT_UNVERIFIED):
        if status in statuses:
            if status == MISSING:
                reasons.append("required_file_missing")
            elif status == INCOMPLETE:
                reasons.append("evidence_incomplete")
            return status, reasons
    # Every required file is byte-verified. Integrity is settled; the capability decides what may be claimed.
    if capability["policy"] in (NEEDS_INTEGRATION, UNSUPPORTED):
        return str(capability["policy"]), list(capability["reason_codes"])
    return VERIFIED, reasons


def _resource_result(resource: CatalogResource, evidence: InstalledEvidence) -> dict[str, Any]:
    files = [_file_result(resource, spec, evidence) for spec in resource.files]
    required = [entry for entry in files if entry["required"]]
    capability = _capability(resource)
    status, reasons = _headline(required, capability)
    runnable = False
    if status == VERIFIED and capability["policy"] == "supported_now":
        if capability["id"].startswith("controlnet_unit."):
            matched = [item for entry in required for item in entry["_candidates"]]
            kinds = {item.controlnet_evidence for item in matched}
            if kinds == {_SDXL}:
                runnable = True
            elif _NOT_SDXL in kinds:
                status, reasons = UNSUPPORTED, ["controlnet_header_not_sdxl"]
            else:
                reasons.append("controlnet_header_unconfirmed")
        else:
            runnable = True
    for entry in files:
        entry.pop("_candidates")
    return {
        "id": resource.id,
        "title": resource.title,
        "category": resource.category,
        "status": status,
        "ready_for_use": runnable,
        "reason_codes": sorted(set(reasons)),
        "missing_roles": [entry["role"] for entry in required if entry["status"] == MISSING],
        "capability": capability,
        "source": resource.source,
        "acquisition": _acquisition(resource, files),
        "files": files,
        "external_prerequisites": [
            {"id": item.id, "kind": item.kind, "state": item.state, "description": item.description}
            for item in resource.external_prerequisites
        ],
        "notes": list(resource.notes),
    }


def build_report(catalog: Catalog, evidence: InstalledEvidence) -> dict[str, Any]:
    """The deterministic, sanitized readiness document (resources sorted by id)."""

    resources = [
        _resource_result(item, evidence) for item in sorted(catalog.resources, key=lambda r: r.id)
    ]
    summary = dict.fromkeys(STATUSES, 0)
    for entry in resources:
        summary[entry["status"]] += 1
    return {
        "contract": REPORT_CONTRACT,
        "catalog": {
            "contract": catalog.contract,
            "version": catalog.version,
            "hash_semantics": catalog.hash_semantics,
            "resource_count": len(catalog.resources),
        },
        "evidence": {
            "basis": evidence.basis,
            "complete": evidence.complete,
            "incomplete_reason": evidence.incomplete_reason,
            "installed_file_count": len(evidence.files),
            "refused_paths": evidence.refused_paths,
        },
        "summary": summary,
        "resources": resources,
    }


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render_console(report: dict[str, Any]) -> str:
    evidence = report["evidence"]
    lines = [
        f"Asset readiness (catalog {report['catalog']['version']}; evidence: {evidence['basis']}, "
        f"{'complete' if evidence['complete'] else 'INCOMPLETE - ' + str(evidence['incomplete_reason'])})",
    ]
    for entry in report["resources"]:
        suffix = f" [{', '.join(entry['reason_codes'])}]" if entry["reason_codes"] else ""
        lines.append(f"- {entry['id']}: {entry['status']}{suffix}")
        if entry["missing_roles"]:
            lines.append(f"    missing: {', '.join(entry['missing_roles'])}")
        for step in entry["acquisition"]["steps"]:
            lines.append(f"    {step}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------------------- collection


def collect_installed_evidence(
    registry: Any,
    catalog: Catalog,
    *,
    refresh: bool,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[Any, int, int], None] | None = None,
    roots: frozenset[str] | None = None,
) -> InstalledEvidence:
    """Gather evidence from the one registry. Worker-only: ``refresh=True`` streams SHA-256 of every file in two roots.

    ``refresh=False`` reads the persisted cache and keeps only entries whose size/mtime fingerprint still matches; it
    can say what is present but never that something is absent, so it is reported as incomplete. ``roots`` limits the
    evidence (and the refresh) to the named catalog roots; a caller that needs one root never pays to hash the other.
    """

    from src.assets.controlnet_structure import inspect_controlnet_file
    from src.assets.registry import AssetKind

    basis = BASIS_REFRESH if refresh else BASIS_CACHE
    if getattr(registry, "webui_root", None) is None:
        return InstalledEvidence((), basis, False, "no_webui_root")
    kind_roots = {
        kind: root
        for kind, root in (
            (AssetKind.CONTROLNET, ROOT_CONTROLNET),
            (AssetKind.AUXILIARY_MODEL, ROOT_AUXILIARY),
        )
        if roots is None or root in roots
    }
    try:
        if refresh:
            snapshot = registry.refresh(
                kinds=set(kind_roots), cancelled=cancelled, progress=progress
            ).snapshot
        else:
            snapshot = registry.cached_snapshot()
    except InterruptedError:
        return InstalledEvidence((), basis, False, "cancelled")
    except TimeoutError:
        return InstalledEvidence((), basis, False, "cache_unavailable")
    except ValueError:
        return InstalledEvidence((), basis, False, "refresh_refused")
    except OSError:
        return InstalledEvidence((), basis, False, "filesystem_error")

    pinned = {root: catalog.pinned_digests(root) for root in kind_roots.values()}
    files: dict[tuple[str, str], InstalledFile] = {}
    refused = 0
    for record in snapshot.records:
        for location in record.locations:
            root = kind_roots.get(location.kind)
            if root is None:
                continue
            try:
                relative = location.path.resolve().relative_to(location.root.resolve()).as_posix()
            except (ValueError, OSError):
                refused += 1  # a link or alias that leaves its library is never evidence
                continue
            if not refresh and registry.verified_sha256(location.path) != record.sha256:
                continue  # a stale cache entry: the file changed or vanished since it was hashed
            evidence_kind = None
            if root == ROOT_CONTROLNET and record.sha256 in pinned[root]:
                evidence_kind = inspect_controlnet_file(location.path).status
            header_error = (
                record.embedded_metadata_error
                if location.path.suffix.lower() == ".safetensors"
                else None
            )
            files[(root, relative)] = InstalledFile(
                root, relative, location.byte_size, record.sha256, header_error, evidence_kind
            )
    ordered = tuple(sorted(files.values(), key=lambda item: (item.root, item.relative.casefold())))
    if len(ordered) > MAX_INSTALLED_FILES:
        return InstalledEvidence(ordered[:MAX_INSTALLED_FILES], basis, False, "file_limit", refused)
    complete = refresh
    return InstalledEvidence(
        ordered, basis, complete, None if complete else "not_refreshed", refused
    )
