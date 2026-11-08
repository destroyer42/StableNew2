"""Operator verdicts on compatibility probes (MEC-902) and the explicit classification they may lead to.

A verdict records what the operator saw after reviewing a probe: whether the checkpoint runs here, which lineage it
looks like, and which recipe was best. It is **advisory** (owner decision D3): it is shown in the Model Evidence
Catalog and never changes a model policy, family, recommendation, Apply or profile by itself.

Classification is a separate explicit decision. ``classification_sidecar`` builds a ``.civitai.info``-style sidecar
whose ``baseModel`` label the existing registry family evidence already reads. It is written only when the checkpoint
has no sidecar at all (never overwriting Civitai's or anyone else's), after the operator confirms the exact path, and
it carries a provenance block saying StableNew wrote it at the operator's request.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.utils.atomic_io import atomic_write_text

CONTRACT = "stablenew_probe_verdict/1"
SIDECAR_CONTRACT = "stablenew_operator_classification/1"

RUNS_YES, RUNS_ARTIFACTS, RUNS_NO = "works", "works_with_artifacts", "does_not_work"
RUNS_LABELS = {
    RUNS_YES: "Works",
    RUNS_ARTIFACTS: "Works, with artifacts",
    RUNS_NO: "Does not work here",
}
#: Lineage -> (display label, ``baseModel`` label the registry family evidence maps to the right family).
LINEAGES: dict[str, tuple[str, str]] = {
    "unknown": ("Not sure", ""),
    "sd15": ("SD 1.5", "SD 1.5"),
    "sd2": ("SD 2.x", "SD 2.1"),
    "sdxl": ("SDXL", "SDXL 1.0"),
    "pony": ("Pony (SDXL-based)", "SDXL 1.0 (Pony)"),
    "illustrious": ("Illustrious (SDXL-based)", "SDXL 1.0 (Illustrious)"),
    "sdxl_turbo": ("SDXL Turbo", "SDXL Turbo"),
    "sdxl_lightning": ("SDXL Lightning / Hyper", "SDXL Lightning"),
    "flux": ("Flux", "Flux.1 D"),
}
_SHA = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class ProbeVerdict:
    sha256: str
    model: str
    runs: str
    lineage: str = "unknown"
    best_recipe: str = ""
    notes: str = ""
    probe_ids: tuple[str, ...] = ()
    recorded_at: str = ""

    def validate(self) -> None:
        if not _SHA.fullmatch(self.sha256):
            raise ValueError("A verdict needs the checkpoint's verified SHA-256.")
        if self.runs not in RUNS_LABELS:
            raise ValueError("Choose whether the checkpoint works.")
        if self.lineage not in LINEAGES:
            raise ValueError("Unknown lineage.")
        if len(self.notes) > 4000 or len(self.best_recipe) > 400:
            raise ValueError("Notes are limited to 4000 characters.")

    def to_dict(self) -> dict[str, Any]:
        return {"contract": CONTRACT, **asdict(self), "probe_ids": list(self.probe_ids)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProbeVerdict:
        if data.get("contract") != CONTRACT:
            raise ValueError("Unsupported verdict document")
        verdict = cls(
            sha256=str(data["sha256"]),
            model=str(data.get("model") or ""),
            runs=str(data["runs"]),
            lineage=str(data.get("lineage") or "unknown"),
            best_recipe=str(data.get("best_recipe") or ""),
            notes=str(data.get("notes") or ""),
            probe_ids=tuple(str(item) for item in data.get("probe_ids") or ()),
            recorded_at=str(data.get("recorded_at") or ""),
        )
        verdict.validate()
        return verdict

    def describe(self) -> list[str]:
        lines = [
            f"{RUNS_LABELS[self.runs]}; looks like {LINEAGES[self.lineage][0]}"
            + (f"; best recipe: {self.best_recipe}" if self.best_recipe else "")
            + (f" (recorded {self.recorded_at[:10]})" if self.recorded_at else "")
        ]
        if self.notes:
            lines.append("Notes: " + " ".join(self.notes.split()))
        return lines


def default_root() -> Path:
    from src.generation_profiles.evidence_catalog import operator_catalog_root

    return operator_catalog_root() / "verdicts"


class VerdictStore:
    """One JSON per checkpoint SHA-256; the latest verdict replaces the earlier one (atomic write)."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_root()

    def path_for(self, sha256: str) -> Path:
        if not _SHA.fullmatch(sha256 or ""):
            raise ValueError("Invalid checkpoint SHA-256")
        return self.root / f"{sha256}.json"

    def save(self, verdict: ProbeVerdict) -> ProbeVerdict:
        verdict.validate()
        if not verdict.recorded_at:
            verdict = ProbeVerdict(
                **{**asdict(verdict), "recorded_at": datetime.now(UTC).isoformat(timespec="seconds")}
            )
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            self.path_for(verdict.sha256), json.dumps(verdict.to_dict(), indent=2, sort_keys=True)
        )
        return verdict

    def load(self, sha256: str) -> ProbeVerdict | None:
        try:
            path = self.path_for(sha256)
            if not path.is_file():
                return None
            return ProbeVerdict.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def load_all(self) -> dict[str, ProbeVerdict]:
        result: dict[str, ProbeVerdict] = {}
        if not self.root.is_dir():
            return result
        for path in self.root.glob("*.json"):
            verdict = self.load(path.stem)
            if verdict is not None:
                result[verdict.sha256] = verdict
        return result


def existing_sidecars(model_path: Path) -> list[Path]:
    """Every sidecar name the registry would read for this checkpoint that already exists."""
    candidates = (
        model_path.with_suffix(model_path.suffix + ".civitai.info"),
        model_path.with_name(f"{model_path.stem}.civitai.info"),
    )
    return [candidate for candidate in candidates if candidate.exists()]


def classification_sidecar(model_path: Path, verdict: ProbeVerdict) -> tuple[Path, dict[str, Any]]:
    """The sidecar path and document an explicit classification would write; raises if it must not be written."""
    verdict.validate()
    label = LINEAGES[verdict.lineage][1]
    if not label:
        raise ValueError("Choose the lineage the probe showed before classifying.")
    if verdict.runs == RUNS_NO:
        raise ValueError("The verdict says this checkpoint does not work here; it is not classified.")
    present = existing_sidecars(model_path)
    if present:
        raise ValueError(
            f"{present[0].name} already exists. StableNew never overwrites a sidecar; edit it yourself if it is wrong."
        )
    document = {
        "baseModel": label,
        "stablenew_operator_classification": {
            "contract": SIDECAR_CONTRACT,
            "lineage": verdict.lineage,
            "sha256": verdict.sha256,
            "probe_ids": list(verdict.probe_ids),
            "best_recipe": verdict.best_recipe,
            "classified_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "note": (
                "Written by StableNew at the operator's explicit request after reviewing a compatibility "
                "probe. Not downloaded from Civitai. Delete this file to undo."
            ),
        },
    }
    return model_path.with_name(f"{model_path.stem}.civitai.info"), document


def write_classification(path: Path, document: Mapping[str, Any]) -> None:
    """Create the sidecar exclusively; a file that appeared meanwhile is never replaced."""
    with path.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
