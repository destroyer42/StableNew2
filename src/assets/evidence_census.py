"""Bounded operator census over the existing registry; no independent scanner/cache."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.assets.observation import ScanLimits
from src.assets.registry import AssetKind, AssetRegistry


@dataclass(frozen=True)
class CensusBudget:
    max_assets: int = 512
    max_hash_bytes: int = 64 * 1024**3
    max_seconds: float = 120.0


def refresh_census(
    registry: AssetRegistry,
    *,
    verify: bool = False,
    budget: CensusBudget = CensusBudget(),
    limits: ScanLimits | None = None,
    cancelled: Callable[[], bool] = lambda: False,
    progress: Callable[[str], None] = lambda _message: None,
) -> dict[str, Any]:
    started = time.monotonic()

    def expired() -> bool:
        return cancelled() or time.monotonic() - started >= budget.max_seconds

    scan = registry.observe(
        limits=limits or ScanLimits(max_files=budget.max_assets), cancelled=expired
    )
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    hashed, hits = 0, 0
    by_hash: dict[str, list[str]] = {}
    for index, item in enumerate(scan.files):
        if index >= budget.max_assets or expired():
            break
        relative = f"{item.root_label}/{item.relative}"
        progress(f"{index + 1}/{len(scan.files)}: {relative}")
        digest = registry.verified_sha256(Path(item.path))
        failure = list(item.errors)
        active = item.root_label != "models/embeddings"
        if verify and active and item.kind in {k.value for k in AssetKind}:
            if not digest and hashed + item.size > budget.max_hash_bytes:
                failure.append("Hash byte budget exhausted; identity pending")
            else:
                read = 0

                def on_bytes(_path: Path, done: int, total: int, label: str = relative) -> None:
                    nonlocal read
                    read = done
                    progress(f"{label}: {done}/{total} bytes")

                try:
                    result = registry.refresh(
                        observed_files=(item,), cancelled=expired, progress=on_bytes
                    )
                    digest = registry.verified_sha256(Path(item.path))
                    hits += result.hash_cache_hits
                except (OSError, ValueError, TimeoutError) as exc:
                    failure.append(type(exc).__name__ + ": identity verification failed")
                finally:
                    hashed += read
        elif digest:
            hits += 1
        record = next((r for r in registry.snapshot.records if r.sha256 == digest), None)
        if item.header and item.header.error:
            failure.append("Header invalid or uninspected: " + item.header.error)
        if record:
            failure.extend(
                "Malformed local sidecar" for location in record.locations if location.sidecar_error
            )
        compatibility = record.compatibility if record else None
        row: dict[str, Any] = {
            "kind": item.kind,
            "relative": relative,
            "size": item.size,
            "identity_status": "verified" if digest else "pending",
            "sha256": digest,
            "active": active,
            "header": asdict(item.header) if item.header else None,
            "metadata": {
                key: value
                for key, value in (item.header.claims.items() if item.header else ())
                if key
                in {
                    "modelspec.architecture",
                    "modelspec.base_model_version",
                    "ss_base_model_version",
                }
                and isinstance(value, str)
                and len(value) < 200
                and not any(c in value for c in ("/", "\\", ":"))
            },
            "compatibility": compatibility.status.value if compatibility else "unknown",
            "family": compatibility.family.value
            if compatibility and compatibility.family
            else "unknown",
            "errors": failure,
            "duplicate_of": None,
        }
        if digest:
            previous = by_hash.setdefault(digest, [])
            row["duplicate_of"] = previous[0] if previous else None
            previous.append(relative)
        rows.append(row)
        errors.extend(f"{relative}: {error}" for error in failure)
    # Only allow-listed, relative metadata is exported. Raw sidecars may contain
    # private URLs, filesystem paths or prompt text and remain in the registry.
    for row in rows:
        header = row["header"] or {}
        row["header"] = {
            key: header.get(key)
            for key in (
                "format",
                "tensor_count",
                "checkpoint_architecture",
                "checkpoint_variant",
                "quantization_formats",
                "error",
            )
        }
    partial = (
        not scan.complete
        or bool(scan.errors)
        or len(rows) != len(scan.files)
        or bool(errors)
        or any(r["identity_status"] != "verified" for r in rows if verify and r["active"])
    )
    return {
        "contract": "model_evidence_census/1",
        "complete": not partial,
        "cancelled": cancelled(),
        "truncated": scan.truncated,
        "counts": dict(sorted(Counter(r["kind"] for r in rows).items())),
        "verified": sum(r["identity_status"] == "verified" for r in rows),
        "hash_bytes": hashed,
        "unchanged": hits,
        "assets": rows,
        "errors": errors + ["Observation error" for _ in scan.errors],
        "skipped": [{"relative": name, "reason": reason} for name, reason in scan.skipped],
        "packages": [
            {
                "id": p.package_id,
                "status": p.status,
                "directory": p.directory,
                "problems": list(p.problems),
            }
            for p in scan.packages
        ],
    }
