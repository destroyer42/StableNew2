"""QUAL-928: the 2026-11-18 ledger refresh stays pinned to the live catalogs it was taken from (CPU only, no host).

``reconcile_with_live`` covers workflow governance and the text AI registry. These checks add the identities it does not
read: the curated ControlNet catalog, the visual candidate catalog and the pinned workflow provenance. A mismatch means
the recorded claim is stale and live state wins.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.video.workflow_catalog import build_builtin_workflow_specs
from tools.operator_journey.workspace import REPO_ROOT
from tools.qualification.system840.ledger import Ledger, applicable_physical, load_ledger
from tools.qualification.system840.statuses import Status


@pytest.fixture(scope="module")
def ledger() -> Ledger:
    return load_ledger()


def _json(relative: str) -> dict:
    return json.loads(Path(REPO_ROOT, relative).read_text(encoding="utf-8"))


def test_controlnet_depth_identity_is_the_catalog_pinned_fp16_variant(ledger: Ledger) -> None:
    entry = ledger.get("IMG-Q2.controlnet-depth")
    assert entry is not None
    resource = next(
        r
        for r in _json("config/curated_asset_catalog.json")["resources"]
        if r["id"] == "sdxl-controlnet-depth"
    )
    variants = [v for f in resource["files"] for v in f.get("variants", [])]
    pinned = next(
        v for v in variants if v["suggested_filename"] == "diffusers_xl_depth_fp16.safetensors"
    )
    assert entry.identity["controlnet"] == "diffusers_xl_depth_fp16"
    assert entry.identity["model_sha256"] == pinned["sha256"]
    assert entry.status == Status.NOT_TESTED and not applicable_physical(entry)


def test_visual_candidates_are_in_the_ledger_with_their_catalog_identity(ledger: Ledger) -> None:
    candidates = _json("config/ai_visual_candidates.json")["candidates"]
    assert {c["candidate_id"] for c in candidates} == {
        "lfm3-vl-2b-q4_k_m-liquidai",
        "gemma-4-12b-it-qat-q4_0-google",
    }
    for candidate in candidates:
        entry = ledger.get(f"AI-Q1.{candidate['candidate_id']}")
        assert entry is not None, candidate["candidate_id"]
        identity = entry.identity
        assert identity["model_id"] == candidate["candidate_id"]
        assert (identity["model"], identity["size"], identity["model_sha256"]) == (
            candidate["model"]["filename"],
            candidate["model"]["bytes"],
            candidate["model"]["sha256"],
        )
        assert (
            identity["projector"],
            identity["projector_size"],
            identity["projector_sha256"],
        ) == (
            candidate["projector"]["filename"],
            candidate["projector"]["bytes"],
            candidate["projector"]["sha256"],
        )
        # The catalog says unqualified and operator-only; the ledger may not say more.
        assert candidate["qualified"] is False and candidate["production_eligible"] is False
        assert entry.status != Status.QUALIFIED
        assert entry.dimension("quality") == Status.NOT_TESTED
        assert entry.dimension("integration") == Status.NOT_TESTED


@pytest.mark.parametrize(
    ("capability", "workflow", "has_eval_evidence"),
    [
        ("VID-Q0.wan22-ti2v-5b-1.4.0", ("wan22_ti2v_5b_i2v_v1", "1.4.0"), True),
        ("VID-Q0.wan22-ti2v-5b-720p-1.0.0", ("wan22_ti2v_5b_i2v_720p_v1", "1.0.0"), False),
        ("VID-Q4.wan22-i2v-a14b-4step-1.0.0", ("wan22_i2v_a14b_4step_v1", "1.0.0"), True),
    ],
)
def test_new_video_candidates_carry_the_pinned_workflow_files(
    ledger: Ledger, capability: str, workflow: tuple[str, str], has_eval_evidence: bool
) -> None:
    entry = ledger.get(capability)
    assert entry is not None
    assert entry.identity["workflow"] == "@".join(workflow)
    spec = next(
        s for s in build_builtin_workflow_specs() if (s.workflow_id, s.workflow_version) == workflow
    )
    provenance = spec.backend_defaults["provenance"]
    assert entry.identity["model_files"] == provenance["files"]
    assert entry.identity["runtime"].endswith(provenance["comfyui_revision"])
    # The VID-CLIP-371 eval ran 1.4.0 and A14B 4-step; the 720p workflow id was created after it, and evidence for a
    # different workflow identity does not count, so that entry stays without applicable physical evidence.
    assert bool(applicable_physical(entry)) is has_eval_evidence
    assert entry.dimension("resource") == Status.NOT_TESTED
    assert entry.dimension("quality") == Status.NOT_TESTED
    assert entry.dimension("integration") == Status.NOT_TESTED


def test_the_two_dropped_qwen_candidates_are_kept_and_recorded_not_pursued(ledger: Ledger) -> None:
    registry = {m["model_id"] for m in _json("config/ai_model_registry.json")["models"]}
    for model_id in ("qwen3.5-9b-q5_k_m-unsloth", "qwen3.5-4b-q8_0-unsloth"):
        entry = ledger.get(f"AI-Q1.{model_id}")
        assert (
            entry is not None and model_id in registry
        )  # the registry is unchanged, so the entry stays
        assert entry.status == Status.HOLD and entry.data["next_test"]["admissible"] is False
        assert "not pursued" in entry.data["governance"]["state"]
