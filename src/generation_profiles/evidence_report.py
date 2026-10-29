"""Portable, informational exports. They never deserialize into executable profiles."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.generation_profiles.evidence_catalog import MAX_BYTES, EvidenceCatalog
from src.learning.evidence_proposals import evidence_gaps
from src.utils.atomic_io import atomic_write_text

CONTRACT = "model_evidence_report/1"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact(item)
            for key, item in value.items()
            if key
            not in {
                "prompt",
                "negative_prompt",
                "prompt_text",
                "negative_prompt_text",
                "baseline",
                "baseline_config",
                "prompt_source_context",
                "path",
                "sidecar_metadata",
            }
        }
    if isinstance(value, (tuple, list)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"\\\\[^\s\"<>]+", "[local path omitted]", value)
        value = re.sub(r"(?<![:/\w])//[^\s\"<>]+", "[local path omitted]", value)
        value = re.sub(r"(?<!\w)[A-Za-z]:[\\/][^\s\"<>]+", "[local path omitted]", value)
        value = re.sub(r"(?<![:/\w])/(?!/)[^\s\"<>]+", "[local path omitted]", value)
    return value


def build_report(
    census: Mapping[str, Any],
    catalog: EvidenceCatalog,
    targets: Sequence[Any] = (),
    proposals: Sequence[Any] = (),
    outcomes: Sequence[Any] = (),
) -> dict[str, Any]:
    checkpoints = []
    for target in targets:
        checkpoints.append(
            {
                "identity": target.identity.to_dict(),
                "policy": target.policy.policy_id,
                "coverage": [
                    {
                        "field": c.field,
                        "status": c.status,
                        "reason": c.reason,
                        "claims": [vars(claim) for claim in c.claims],
                    }
                    for c in catalog.coverage(
                        target.identity,
                        variant=target.identity.key if target.policy.qualified else "",
                    )
                ],
                "gaps": [vars(g) for g in evidence_gaps(catalog, target)],
            }
        )
    return validate_report(
        _redact(
            {
                "contract": CONTRACT,
                "catalog_revision": catalog.revision,
                "census": dict(census),
                "checkpoints": checkpoints,
                "proposals": [dict(p.document) for p in proposals],
                "outcomes": list(outcomes),
                "limitations": [
                    "Research is not execution qualification.",
                    "No physical generation performed by this package.",
                    "Absent historical provenance is unavailable; it is never reconstructed from current research.",
                    "Unsupported families/accelerators and unqualified geometry remain blocked or metadata-only.",
                ],
            }
        )
    )


def validate_report(raw: Any) -> dict[str, Any]:
    keys = {
        "contract",
        "catalog_revision",
        "census",
        "checkpoints",
        "proposals",
        "outcomes",
        "limitations",
    }
    if not isinstance(raw, dict) or set(raw) != keys or raw.get("contract") != CONTRACT:
        raise ValueError("Unsupported evidence report")
    if not re.fullmatch(r"[0-9a-f]{64}", raw.get("catalog_revision", "")) or not isinstance(
        raw["census"], dict
    ):
        raise ValueError("Invalid report provenance")
    if any(
        not isinstance(raw[k], list)
        for k in ("checkpoints", "proposals", "outcomes", "limitations")
    ):
        raise ValueError("Invalid report sections")
    for checkpoint in raw["checkpoints"]:
        if (
            not isinstance(checkpoint, dict)
            or not isinstance(checkpoint.get("identity"), dict)
            or not isinstance(checkpoint.get("coverage"), list)
            or not isinstance(checkpoint.get("gaps"), list)
        ):
            raise ValueError("Invalid checkpoint report")
    for proposal in raw["proposals"]:
        if (
            not isinstance(proposal, dict)
            or proposal.get("contract")
            not in {"qualification_proposal/1", "qualification_proposal/2"}
            or not isinstance(proposal.get("name"), str)
            or proposal.get("status")
            not in (
                {"draft", "blocked", "metadata_only"}
                if proposal.get("contract") == "qualification_proposal/2"
                else {"draft", "blocked"}
            )
            or (
                proposal.get("expected_images") not in {12, 15, 20}
                and not (
                    proposal.get("contract") == "qualification_proposal/2"
                    and proposal.get("status") in {"blocked", "metadata_only"}
                    and proposal.get("expected_images") == 0
                )
            )
        ):
            raise ValueError("Invalid proposal report")
    if any(not isinstance(outcome, dict) for outcome in raw["outcomes"]) or any(
        not isinstance(item, str) for item in raw["limitations"]
    ):
        raise ValueError("Invalid outcome/limitation report")
    encoded = json.dumps(raw, allow_nan=False)
    if len(encoded.encode()) > MAX_BYTES * 8:
        raise ValueError("Report exceeds limit")
    return dict(json.loads(encoded))


def render_report(report: Mapping[str, Any]) -> str:
    report = validate_report(dict(report))
    census = report["census"]
    lines = [
        "# Model Evidence Catalog",
        "",
        f"Evidence revision: {report['catalog_revision']}",
        f"Census complete: {census.get('complete', False)}; verified identities: {census.get('verified', 0)}; unchanged: {census.get('unchanged', 0)}",
        "",
        "## Census by type",
        "",
        *[f"- {kind}: {count}" for kind, count in census.get("counts", {}).items()],
        "",
    ]
    for checkpoint in report["checkpoints"]:
        lines.extend(
            [
                f"## {checkpoint['identity']['display_name']}",
                "",
                f"Policy: {checkpoint['policy']}",
                "",
            ]
        )
        for field in checkpoint["coverage"]:
            claims = "; ".join(
                f"{c['value']} [{c['classification']}, {c['confidence']}, reviewed {c['reviewed_on']}] {c['source']} {c['caveat']}"
                for c in field["claims"]
            )
            lines.append(f"- {field['field']}: {field['status']}. {claims or field['reason']}")
        lines.extend(
            [
                "",
                "Prioritized gaps:",
                "",
                *[
                    f"- {g['priority']} {g['variable']}: {g['status']} — {g['reason']}"
                    for g in checkpoint["gaps"]
                ],
                "",
            ]
        )
    lines.extend(["## Proposed experiments", ""])
    for proposal in report["proposals"]:
        lines.extend(
            [
                f"- {proposal['name']} ({proposal['status']}, {proposal['expected_images']} images)",
                f"  {proposal['hypothesis']} {'; '.join(proposal['blocked_reasons'])}",
            ]
        )
    lines.extend(
        [
            "",
            "## Outcomes",
            "",
            *[json.dumps(outcome, ensure_ascii=False) for outcome in report["outcomes"]],
            "No outcome exists until the operator runs and reviews an experiment."
            if not report["outcomes"]
            else "",
            "",
            "## Unresolved issues",
            "",
            *[f"- {issue}" for issue in census.get("errors", [])],
            *[f"- {limitation}" for limitation in report["limitations"]],
        ]
    )
    return "\n".join(lines) + "\n"


def export_report(root: Path, report: Mapping[str, Any]) -> tuple[Path, Path]:
    document = validate_report(dict(report))
    root.mkdir(parents=True, exist_ok=True)
    stem = "model-evidence-" + document["catalog_revision"][:12]
    machine, readable = root / f"{stem}.json", root / f"{stem}.md"
    atomic_write_text(machine, json.dumps(document, indent=2, ensure_ascii=False))
    atomic_write_text(readable, render_report(document))
    return machine, readable
