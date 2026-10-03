"""PR-COMFY-RUNTIME-100: workflow 1.2.0 is the 1.1.0 graph requalified on the managed runtime.

Deterministic, GPU-free. Historical versions must stay byte-identical (jobs replay against the exact
pinned graph), and 1.2.0 may differ from 1.1.0 only in version identity and qualification
provenance: same graph, model hashes, controls, frame policy, launch requirement and readiness
floors. The physical runs are the runtime evidence; these tests pin what must not move.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.video.comfy_workflow_backend import _actual_runtime_identity
from src.video.workflow_catalog import WAN22_RUNTIME_PROVENANCE, WAN22_RUNTIME_VERSION
from src.video.workflow_catalog_wan_animate2 import (
    WAN_ANIMATE2_DRIVE_ID,
    WAN_ANIMATE2_PROMPT_ID,
    WAN_ANIMATE2_RUNTIME_PROVENANCE,
    WAN_ANIMATE2_RUNTIME_VERSION,
)
from src.video.workflow_registry import build_default_workflow_registry
from tests.video.test_wan22_experimental_workflow import (
    WAN_ID,
    _backend,
    _FakeComfy,
    _request,
    _stats,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads((ROOT / "config" / "managed_comfy_runtime.json").read_text(encoding="utf-8"))
WORKFLOW_IDS = (WAN_ID, WAN_ANIMATE2_PROMPT_ID, WAN_ANIMATE2_DRIVE_ID)

# sha256 of json.dumps(spec.to_dict(), sort_keys=True, ensure_ascii=False, default=str) and of the
# prompt template alone, captured from the registry before PR-COMFY-RUNTIME-100 touched it.
HISTORICAL_SPEC_SHA256 = {
    (WAN_ID, "1.0.0"): "2dd94ae24001fe7d71d83f871b9a50059518255ddfb82cd40b4294cea6dfc70b",
    (WAN_ID, "1.1.0"): "ac57e2952d9a97a99e2f8d195fe0c41d96ddc0164d6c68b0344d74255af287f4",
    (WAN_ANIMATE2_DRIVE_ID, "1.0.0"): "e92757007f29bff27bd0c84c829c68fb8f934b11e6181b705b75d1f03cdf3510",
    (WAN_ANIMATE2_DRIVE_ID, "1.1.0"): "c5a8ab613ea8e130f27250596be0aac17cb8d96399386ef36456b6fb37608fa0",
    (WAN_ANIMATE2_PROMPT_ID, "1.0.0"): "fa3eed00ba5ce134f2f7fab4ce9c94abbc60f7de05efecb6bd3fc8b1206fceac",
    (WAN_ANIMATE2_PROMPT_ID, "1.1.0"): "75d1778e665015f4da4507d34ea165b3d9881eef3fcdab197d12f7c6bc12ed1c",
}
HISTORICAL_TEMPLATE_SHA256 = {
    (WAN_ID, "1.0.0"): "116e980387bc763c5a598641b81ead80201a2615ad19cdc625b4eb4da1484154",
    (WAN_ID, "1.1.0"): "9d7cd16b2101435ac51c26c5cf1395951ed2e95776217cfa699ebf54c0836eba",
    (WAN_ANIMATE2_DRIVE_ID, "1.0.0"): "d6bfd4e1d7298f4fb7b520ddc0148b5191d2ee79d1d9e86ed310083a6d2541d1",
    (WAN_ANIMATE2_DRIVE_ID, "1.1.0"): "a371227170de97e5a83c154822735a937a3e7ec271bd02ed627c797c442f3065",
    (WAN_ANIMATE2_PROMPT_ID, "1.0.0"): "12d0d1777aeaaf5d7e5867de9f82bb2a5b7b171f3a6d1fd6c0f97a152ba9ff87",
    (WAN_ANIMATE2_PROMPT_ID, "1.1.0"): "9706fcb823a29ba5e0b0d40c48a3fdc3bde46a1f26b3b5a79ca1abbc6def87f1",
}


def _spec(workflow_id: str, version: str):
    return build_default_workflow_registry().get(workflow_id, version, allow_experimental=True)


def _digest(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _differences(left: Any, right: Any, path: str = "") -> set[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        found: set[str] = set()
        for key in set(left) | set(right):
            found |= _differences(left.get(key), right.get(key), f"{path}.{key}" if path else key)
        return found
    return set() if left == right else {path}


# --- Historical versions never move -----------------------------------------------------------


@pytest.mark.parametrize(("workflow_id", "version"), sorted(HISTORICAL_SPEC_SHA256))
def test_historical_versions_stay_byte_identical(workflow_id: str, version: str) -> None:
    spec = _spec(workflow_id, version)

    assert _digest(spec.to_dict()) == HISTORICAL_SPEC_SHA256[(workflow_id, version)]
    assert _digest(spec.backend_defaults["prompt_template"]) == HISTORICAL_TEMPLATE_SHA256[(workflow_id, version)]


def test_historical_provenance_is_not_rewritten_to_the_new_runtime() -> None:
    assert _spec(WAN_ID, "1.0.0").backend_defaults["provenance"]["comfyui_version"] == "0.3.65"
    assert _spec(WAN_ID, "1.1.0").backend_defaults["provenance"]["comfyui_version"] == "0.3.65"
    for workflow_id in (WAN_ANIMATE2_PROMPT_ID, WAN_ANIMATE2_DRIVE_ID):
        for version in ("1.0.0", "1.1.0"):
            provenance = _spec(workflow_id, version).backend_defaults["provenance"]
            assert provenance["comfyui_version"] == "0.37.0"
            assert provenance["comfyui_revision"] == "73c9bad4d21e7addbe1d13bc92eee0f1431b017d"


# --- 1.2.0 is the 1.1.0 graph, requalified ----------------------------------------------------


@pytest.mark.parametrize("workflow_id", WORKFLOW_IDS)
def test_new_versions_are_registered_beside_the_old_ones(workflow_id: str) -> None:
    registry = build_default_workflow_registry()

    assert registry.list_versions(workflow_id) == ["1.0.0", "1.1.0", "1.2.0"]
    assert WAN22_RUNTIME_VERSION == WAN_ANIMATE2_RUNTIME_VERSION == "1.2.0"
    newest = _spec(workflow_id, "1.2.0")
    assert newest.pinned_revision == f"catalog:{workflow_id}@1.2.0"
    assert newest.governance_state == "experimental"  # no promotion beyond experimental


@pytest.mark.parametrize("workflow_id", WORKFLOW_IDS)
def test_only_version_identity_and_qualification_provenance_differ_from_1_1_0(workflow_id: str) -> None:
    older = _spec(workflow_id, "1.1.0").to_dict()
    newest = _spec(workflow_id, "1.2.0").to_dict()

    assert _differences(older, newest) == {
        "workflow_version",
        "pinned_revision",
        "backend_defaults.provenance.qualification",
        "backend_defaults.provenance.comfyui_version",
        "backend_defaults.provenance.comfyui_revision",
    }


@pytest.mark.parametrize("workflow_id", WORKFLOW_IDS)
def test_graph_model_hashes_controls_and_readiness_floors_are_unchanged(workflow_id: str) -> None:
    older = _spec(workflow_id, "1.1.0")
    newest = _spec(workflow_id, "1.2.0")

    assert _digest(newest.backend_defaults["prompt_template"]) == _digest(older.backend_defaults["prompt_template"])
    assert _digest(newest.backend_defaults["prompt_template"]) == HISTORICAL_TEMPLATE_SHA256[(workflow_id, "1.1.0")]
    assert newest.backend_defaults["provenance"]["files"] == older.backend_defaults["provenance"]["files"]
    assert newest.dependency_specs == older.dependency_specs
    assert newest.input_bindings == older.input_bindings
    # Readiness floors are not lowered, and the launch requirement stays.
    assert newest.backend_defaults["resource_readiness"] == older.backend_defaults["resource_readiness"]
    assert newest.backend_defaults["resource_readiness"]["min_available_to_comfy_vram_mib"] == 10000
    assert newest.backend_defaults["resource_readiness"]["min_available_ram_gb"] == 16.0
    assert newest.backend_defaults["runtime_policy"] == older.backend_defaults["runtime_policy"]
    assert newest.backend_defaults["frame_count_policy"] == older.backend_defaults["frame_count_policy"]
    assert newest.backend_defaults.get("history_timeout_seconds") == older.backend_defaults.get("history_timeout_seconds")
    if workflow_id != WAN_ID:
        assert newest.backend_defaults["operator_controls"] == older.backend_defaults["operator_controls"]
        assert newest.backend_defaults["provenance"]["qualified_graph_sha256"] == (
            older.backend_defaults["provenance"]["qualified_graph_sha256"]
        )


def test_new_provenance_matches_the_managed_runtime_contract() -> None:
    upstream = MANIFEST["upstream"]

    for provenance in (WAN22_RUNTIME_PROVENANCE, WAN_ANIMATE2_RUNTIME_PROVENANCE):
        assert provenance["comfyui_version"] == upstream["version"]
        assert provenance["comfyui_revision"] == upstream["revision"]
        assert "PR-COMFY-RUNTIME-100" in provenance["qualification"]
    for workflow_id in WORKFLOW_IDS:
        newest = _spec(workflow_id, "1.2.0")
        required = set(newest.backend_defaults["runtime_policy"].get("required_launch_flags") or [])
        assert required <= set(MANIFEST["launch_policy"]["required_flags"])  # the runtime launches with them


@pytest.mark.parametrize("workflow_id", [WAN_ANIMATE2_PROMPT_ID, WAN_ANIMATE2_DRIVE_ID])
def test_animate2_new_versions_keep_the_pinned_files_and_the_qualified_graph_hash(workflow_id: str) -> None:
    provenance = _spec(workflow_id, "1.2.0").backend_defaults["provenance"]

    assert provenance["qualified_graph_sha256"] == (
        "9ef8dae44d330e5af05c70fccd02d86d0855b4fb983d1913f8f7f8a012c3928c"
    )
    assert provenance["files"]["wan_animate_2_distill_int8_convrot.safetensors"].startswith("d2e566ecac3f164c")


# --- Actual-runtime identity (observed, recorded in metadata only) -----------------------------


def test_actual_runtime_identity_reads_the_servers_own_report_and_omits_what_it_lacks() -> None:
    stats = {
        "system": {
            "comfyui_version": "0.38.0",
            "python_version": "3.13.16 (tags/v3.13.16:cbc944f, Sep 30 2026) [MSC v.1944 64 bit (AMD64)]",
            "pytorch_version": "2.14.0+cu130",
            "required_frontend_version": "1.53.6",
            "argv": ["--do-not-record"],
        }
    }

    assert _actual_runtime_identity(stats) == {
        "comfyui_version": "0.38.0",
        "python_version": "3.13.16",
        "pytorch_version": "2.14.0+cu130",
        "frontend_version": "1.53.6",
    }
    assert _actual_runtime_identity({"system": {"comfyui_version": "0.38.0"}}) == {"comfyui_version": "0.38.0"}
    for unusable in ({}, {"system": None}, {"system": "x"}, None, "stats", []):
        assert _actual_runtime_identity(unusable) == {}


def test_a_job_records_the_runtime_that_actually_served_it(tmp_path) -> None:
    stats = _stats(free_mib=11000)
    stats["system"] = {"comfyui_version": "0.38.0", "pytorch_version": "2.14.0+cu130"}
    client = _FakeComfy(tmp_path, stats=stats)

    result = _backend(client).execute(SimpleNamespace(), _request(tmp_path, opt_in=True))

    assert result.backend_metadata["actual_runtime"] == {
        "comfyui_version": "0.38.0",
        "pytorch_version": "2.14.0+cu130",
    }
    [manifest_file] = list((tmp_path / "run").glob("manifests/*.json"))
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["actual_runtime"]["comfyui_version"] == "0.38.0"  # recorded for any version run


def test_a_server_that_reports_nothing_adds_no_runtime_record(tmp_path) -> None:
    client = _FakeComfy(tmp_path)  # stats carry devices only

    result = _backend(client).execute(SimpleNamespace(), _request(tmp_path, opt_in=True))

    assert "actual_runtime" not in result.backend_metadata
