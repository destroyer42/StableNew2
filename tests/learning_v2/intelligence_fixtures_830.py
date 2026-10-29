"""Synthetic, hermetic builders for Learning evidence intelligence tests (no backend, model, GPU or network)."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from src.generation_profiles.evidence_catalog import Claim, EvidenceCatalog, EvidenceRecord
from src.generation_profiles.identity import ModelIdentityResolver
from src.generation_profiles.store import GenerationProfileStore
from src.image_backends.model_policy import resolve_model_policy
from src.learning.evidence_autopilot import EvidenceProposalPlanner, ProposalPlanningContext
from src.learning.evidence_intelligence import IntelligenceSources, assess, load_sources
from src.learning.experiment_execution import freeze_snapshot, snapshot_digest
from src.learning.experiment_store import LearningExperimentStore
from src.learning.model_capabilities import policy_context
from src.learning.profile_publication import ProfilePublicationService

MODEL = "test.safetensors"
SHA = "a" * 64
PROMPT = "a lighthouse at dusk PRIVATE-PROMPT-CANARY"
NOTE = "PRIVATE-NOTE-CANARY"
PRIVATE_PATH = "C:/Users/rob/private-images/out"

RESOURCES = {
    "models": [MODEL],
    "samplers": ["Euler", "DPM++ 2M"],
    "schedulers": ["Normal", "Karras", "Automatic"],
    "vaes": [],
}
BASELINE = {
    "txt2img": {
        "model": MODEL,
        "vae": "",
        "steps": 30,
        "cfg_scale": 7.0,
        "sampler_name": "Euler",
        "scheduler": "Normal",
        "width": 1024,
        "height": 1024,
        "seed": 42,
    },
    "backend_options": {"image": {"backend_id": "forge_webui"}},
}


def resolver(sha: str | None = SHA) -> ModelIdentityResolver:
    policy = resolve_model_policy(
        MODEL,
        family_lookup=lambda _name: SimpleNamespace(
            status=SimpleNamespace(value="resolved"), family=SimpleNamespace(value="sdxl")
        ),
    )
    return ModelIdentityResolver(policy_resolver=lambda _name: policy, sha_lookup=lambda _name: sha)


def conflicting_steps_catalog(sha: str = SHA) -> EvidenceCatalog:
    """Two high-confidence exact-checkpoint claims that disagree about steps."""

    def claim(value: int) -> Claim:
        return Claim(
            "steps",
            value,
            "exact_publisher",
            f"https://example.com/source-{value}",
            "2026-10-28",
            f"Publisher card says {value}",
            "high",
        )

    return EvidenceCatalog(
        (
            EvidenceRecord(
                "steps-conflict", "checkpoint", "sdxl", "exact", (claim(30), claim(40)), sha256=sha
            ),
        )
    )


def make_context(
    catalog: EvidenceCatalog | None = None,
    *,
    sha: str | None = SHA,
    baseline: dict[str, Any] | None = None,
    resources: dict[str, Any] | None = None,
) -> ProposalPlanningContext:
    target = resolver(sha).resolve(MODEL)
    return ProposalPlanningContext(
        target,
        conflicting_steps_catalog() if catalog is None else catalog,
        copy.deepcopy(baseline or BASELINE),
        copy.deepcopy(resources or RESOURCES),
    )


def publication_service(tmp_path: Path) -> ProfilePublicationService:
    return ProfilePublicationService(GenerationProfileStore(tmp_path / "profiles"), resolver())


def steps_proposal(context: ProposalPlanningContext) -> dict[str, Any]:
    plan = EvidenceProposalPlanner().plan(context)
    return next(
        p.document for p in plan.proposals if p.runnable and p.document["variable"] == "steps"
    )


def rating_rows(
    experiment_id: str,
    *,
    values: tuple[int, ...] = (30, 40),
    per_value: int = 6,
    rating: Any = None,
    prompt: str = PROMPT,
    flags: dict[str, bool] | None = None,
    model_sha: str = SHA,
    controlled: bool = True,
    skip: set[tuple[int, int]] | None = None,
    notes: str = NOTE,
) -> list[dict[str, Any]]:
    """Saved controlled-rating rows for one experiment. ``rating(value, index)`` gives the overall score."""
    rating = rating or (lambda value, _i: 4 if value == values[-1] else 3)
    target = resolver(model_sha).resolve(MODEL)
    baseline = {**BASELINE["txt2img"], "steps": values[0]}
    seeds = [100 + i for i in range(per_value)]
    snapshot = {
        "schema_version": 2,
        "experiment_id": experiment_id,
        "stage": "txt2img",
        "variable_under_test": "Steps",
        "variant_values": list(values),
        "model_identity": target.identity.to_dict(),
        "model_policy_context": policy_context(target.policy, MODEL, "txt2img"),
        "baseline_config": {"txt2img": baseline},
        "seed_policy": {"requested_sample_count": per_value, "requested_base_seed": 100},
        "prompt_text": prompt,
        "negative_prompt_text": "",
    }
    rows = []
    for vi, value in enumerate(values):
        for i in range(per_value):
            if skip and (vi, i) in skip:
                continue
            overall = rating(value, i)
            rows.append(
                {
                    "run_id": f"{experiment_id}-{vi}-{i}",
                    "primary_model": MODEL,
                    "metadata": {
                        "record_kind": "learning_experiment_rating",
                        "experiment_id": experiment_id,
                        "job_id": f"{experiment_id}-job-{vi}",
                        "image_path": image_path(experiment_id, vi, i),
                        "variable_under_test": "Steps",
                        "variant_value": value,
                        "user_rating": overall,
                        "user_rating_raw": overall,
                        "user_notes": notes,
                        "rating_context": dict(flags or {}),
                        "learning_context": {
                            "experiment_id": experiment_id,
                            "variant_id": f"v{vi}",
                        },
                        "frozen_experiment": {
                            "experiment_id": experiment_id,
                            "variant_id": f"v{vi}",
                            "snapshot": copy.deepcopy(snapshot),
                            "snapshot_sha256": snapshot_digest(freeze_snapshot(snapshot)),
                            "controlled_evidence_valid": controlled,
                            "variable_validation_reason": "valid"
                            if controlled
                            else "backend_restart_boundary",
                            "actual_all_seeds": seeds,
                            "executed_config": {
                                "txt2img": {**baseline, "steps": value, "seed": seeds[0]}
                            },
                        },
                    },
                }
            )
    return rows


def image_path(experiment_id: str, variant_index: int, index: int) -> str:
    return f"{PRIVATE_PATH}/{experiment_id}/v{variant_index}-{index}.png"


def save_experiment(
    store: LearningExperimentStore,
    experiment_id: str,
    *,
    values: tuple[int, ...] = (30, 40),
    per_value: int = 6,
    prompt: str = PROMPT,
    proposal: dict[str, Any] | None = None,
    model_sha: str = SHA,
    controlled: bool | None = True,
    reason: str = "valid",
    status: str = "completed",
    frozen: bool = True,
) -> None:
    target = resolver(model_sha).resolve(MODEL)
    seeds = [100 + i for i in range(per_value)]
    snapshot = {
        "stage": "txt2img",
        "variable_under_test": "Steps",
        "variant_values": list(values),
        "model_identity": target.identity.to_dict(),
        "prompt_text": prompt,
        "negative_prompt_text": "",
    }
    metadata: dict[str, Any] = {}
    if proposal is not None:
        metadata["evidence_proposal"] = proposal
        snapshot["evidence_proposal"] = proposal
    plan = [
        {
            "experiment_id": experiment_id,
            "variant_id": f"v{vi}",
            "param_value": value,
            "status": status,
            "image_refs": [image_path(experiment_id, vi, i) for i in range(per_value)],
            "execution_metadata": {
                "controlled_evidence_valid": controlled,
                "variable_validation_reason": reason,
                "actual_all_seeds": seeds,
            },
        }
        for vi, value in enumerate(values)
    ]
    store.save_session(
        display_name=experiment_id,
        experiment_id=experiment_id,
        payload={
            "current_experiment": {
                "name": experiment_id,
                "experiment_id": experiment_id,
                "stage": "txt2img",
                "variable_under_test": "Steps",
                "values": list(values),
                "metadata": metadata,
                "execution_snapshot_json": json.dumps(snapshot) if frozen else "",
            },
            "plan": plan,
        },
    )


def write_log(path: Path, rows: list[dict[str, Any]], *, extra: str = "") -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows) + extra, encoding="utf-8")
    return path


def run(
    tmp_path: Path,
    *,
    context: ProposalPlanningContext | None = None,
    rows: list[dict[str, Any]] | None = None,
    publication: bool = False,
    log_extra: str = "",
) -> tuple[Any, IntelligenceSources]:
    """Assess with a temporary rating log and experiment store."""
    context = context or make_context()
    log = write_log(tmp_path / "learning_records.jsonl", rows or [], extra=log_extra)
    store = LearningExperimentStore(tmp_path / "experiments")
    sources = load_sources(
        context,
        records_path=log,
        store=store,
        publication_service=publication_service(tmp_path) if publication else None,
    )
    return assess(sources), sources


def reassess(sources: IntelligenceSources, **changes: Any) -> Any:
    return assess(replace(sources, **changes))
