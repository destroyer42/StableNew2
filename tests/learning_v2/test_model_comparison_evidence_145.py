"""PR-LEARN-COMPARE-145: policy-driven Model Comparison evidence and eligibility, on cold and warm registries.

Everything runs through the real ``prepare_comparison_evidence`` and the real registry over tiny temporary
safetensors fixtures: no WebUI, Forge, GPU, installed model or injected family policy.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.assets import AssetRegistry
from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState
from src.image_backends.forge_klein_lora import KleinLoraDecision, KleinLoraStatus
from src.image_backends.forge_klein_profile import KLEIN_PROFILE_V1
from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1 as ZP
from src.learning.execution_controller import LearningExecutionController
from src.learning.experiment_execution import thaw_snapshot
from src.learning.model_comparison import build_comparison_snapshot
from src.learning.model_evidence_readiness import prepare_comparison_evidence
from tests.assets.checkpoint_fixtures import checkpoint, tensor_checkpoint
from tests.learning_v2.test_model_comparison_compat_158 import shared_baseline, study

KLEIN = KLEIN_PROFILE_V1.transformer.filename
ZIMAGE = ZP.transformer.filename
SDXL_META = {"modelspec.architecture": "stable-diffusion-xl-v1-base"}


class World:
    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "webui"
        self.folder = self.root / "models" / "Stable-diffusion"
        self.cache = tmp_path / "state" / "asset_registry_v1.json"
        self.tmp_path = tmp_path

    def registry(self) -> AssetRegistry:
        return AssetRegistry(self.root, cache_path=self.cache)

    def prepare(self, files: dict[str, Path], **kwargs):
        resources = [
            {"model_name": name, "title": f"{name} [1234567890]", "filename": str(path)}
            for name, path in files.items()
        ]
        registry = kwargs.pop("registry", None) or self.registry()
        evidence = prepare_comparison_evidence(list(files), resources, registry=registry, **kwargs)
        return evidence, registry

    def sdxl(self, name: str, *, metadata=None, payload: bytes = b"sdxl") -> Path:
        return checkpoint(self.folder / name, metadata=metadata or SDXL_META, payload=payload)

    def opaque(self, name: str, payload: bytes = b"opaque-bytes-no-header-evidence") -> Path:
        """Neither SDXL metadata nor structure: only an exact profile may admit this file."""

        return checkpoint(self.folder / name, metadata={}, payload=payload)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_exact_zimage_is_the_identity_authority_without_sdxl_gating_or_hashing(world: World) -> None:
    files = {"ordinary": world.sdxl("ordinary.safetensors"), ZIMAGE: world.opaque(ZIMAGE)}
    evidence, registry = world.prepare(files)
    assert evidence.model_identities[ZIMAGE] == {
        "authority": "exact_profile",
        "profile_ref": ZP.reference(),
    }
    assert evidence.model_identities["ordinary"]["authority"] == "asset_registry"
    assert registry.last_refresh.hashes_computed == 1  # only the ordinary checkpoint paid for a byte identity
    document = json.loads(world.cache.read_text(encoding="utf-8"))
    assert [Path(key).name for key in document["entries"]] == ["ordinary.safetensors"]


@pytest.mark.parametrize("exact", [KLEIN, ZIMAGE])
def test_exact_profile_candidate_warm_process_does_no_registry_work(world: World, exact: str, monkeypatch) -> None:
    files = {"ordinary": world.sdxl("ordinary.safetensors"), exact: world.opaque(exact)}
    first, _ = world.prepare(files)
    monkeypatch.setattr(AssetRegistry, "refresh", lambda *a, **k: pytest.fail("warm refresh"))
    monkeypatch.setattr(AssetRegistry, "inspect_checkpoint", lambda *a, **k: pytest.fail("warm header read"))
    second, registry = world.prepare(files)
    assert second.model_identities == first.model_identities
    assert registry.last_refresh.hashes_computed == 0


def test_two_exact_profiles_need_no_registry_cache_at_all(world: World) -> None:
    files = {KLEIN: world.opaque(KLEIN), ZIMAGE: world.opaque(ZIMAGE, b"another opaque payload")}
    evidence, registry = world.prepare(files)
    assert {item["authority"] for item in evidence.model_identities.values()} == {"exact_profile"}
    assert not world.cache.exists()
    assert registry.last_refresh.hashes_computed == 0


def test_exact_profile_still_requires_the_served_file_to_be_accessible(world: World) -> None:
    files = {"ordinary": world.sdxl("ordinary.safetensors"), ZIMAGE: world.opaque(ZIMAGE)}
    files[ZIMAGE].unlink()
    with pytest.raises(ValueError, match="Model 2: .*served checkpoint is unavailable locally"):
        world.prepare(files)


# -- ordinary SDXL derivatives: evidence, not names ------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "metadata", "structural"),
    [
        ("standard_sdxl", SDXL_META, False),
        ("ponyDiffusionV6XL", {"ss_base_model_version": "pony_v6"}, True),  # unrecognized label, SDXL structure
        ("sdxlLightning4step", {"modelspec.architecture": "stable-diffusion-xl-v1-base/lightning"}, False),
        ("turbo_metadata_free", {}, True),  # no metadata at all: layout alone resolves SDXL
    ],
)
def test_evidenced_sdxl_derivatives_are_admitted_through_the_sdxl_policy(
    world: World, name: str, metadata: dict, structural: bool
) -> None:
    path = (
        tensor_checkpoint(world.folder / f"{name}.safetensors", metadata=metadata)
        if structural
        else world.sdxl(f"{name}.safetensors", metadata=metadata)
    )
    other = world.sdxl("peer.safetensors", payload=b"peer")
    evidence, _ = world.prepare({name: path, "peer": other})
    policy = evidence.policy_for(name)
    assert (policy.policy_id, policy.family, policy.evidence) == ("sdxl", "sdxl", "registry_evidence")
    identity = evidence.model_identities[name]
    assert identity["authority"] == "asset_registry" and len(identity["sha256"]) == 64
    assert identity["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("name", ["ponyDiffusionV6XL", "sdxl_lightning_4step", "SDXL-Turbo", "sd15_dreamshaper"])
def test_a_filename_alone_never_manufactures_family_evidence(world: World, name: str) -> None:
    named_only = checkpoint(world.folder / f"{name}.safetensors", metadata={}, payload=b"opaque")
    peer = world.sdxl("peer.safetensors", payload=b"peer")
    with pytest.raises(ValueError, match=r"Model 1: .*(structure unrecognized|metadata missing)"):
        world.prepare({name: named_only, "peer": peer})
    assert not world.cache.exists()  # rejected on its header, before any byte identity was paid for


def test_derivative_and_standard_sdxl_plan_one_study_with_their_own_frozen_identities(world: World) -> None:
    pony = tensor_checkpoint(world.folder / "pony.safetensors", metadata={"ss_base_model_version": "pony_v6"})
    standard = world.sdxl("standard.safetensors")
    evidence, _ = world.prepare({"pony": pony, "standard": standard})
    exp = study(world.tmp_path, models=["pony", "standard"])
    snapshot = build_comparison_snapshot(exp, shared_baseline(), evidence=evidence)
    arms = snapshot["model_comparison"]["arms"]
    assert [arm["model_policy_context"]["family"] for arm in arms] == ["sdxl", "sdxl"]
    assert arms[0]["checkpoint_evidence"]["sha256"] != arms[1]["checkpoint_evidence"]["sha256"]
    assert all(arm["checkpoint_evidence"]["authority"] == "asset_registry" for arm in arms)
    assert arms[0]["source_intent_sha256"] == arms[1]["source_intent_sha256"]


# -- families that are evidenced but have no explicit executable capability policy ---------------------------------


@pytest.mark.parametrize(
    ("metadata", "label"),
    [
        ({"ss_base_model_version": "sd_v1.5"}, "sd1"),
        ({"modelspec.architecture": "stable-diffusion-v2"}, "sd2"),
        ({"modelspec.architecture": "stable-diffusion-v3"}, "sd3"),
        ({"modelspec.architecture": "flux-1-dev"}, "flux"),
    ],
)
def test_evidenced_non_sdxl_families_fail_closed_until_an_explicit_policy_exists(
    world: World, metadata: dict, label: str
) -> None:
    other = world.sdxl("peer.safetensors", payload=b"peer")
    candidate = checkpoint(world.folder / "candidate.safetensors", metadata=metadata, payload=b"c")
    with pytest.raises(ValueError, match=rf"Model 1: .*{label}.*explicit executable capability policy"):
        world.prepare({"candidate": candidate, "peer": other})
    assert not world.cache.exists()


def test_a_structurally_evidenced_non_sdxl_layout_is_rejected_by_policy_not_by_a_family_special_case(
    world: World,
) -> None:
    sd1 = checkpoint(world.folder / "sd1.safetensors", metadata={"ss_base_model_version": "sd_v1.5"})
    peer = world.sdxl("peer.safetensors", payload=b"peer")
    with pytest.raises(ValueError, match="no explicit executable capability policy"):
        world.prepare({"sd1": sd1, "peer": peer})


@pytest.mark.parametrize(
    "case",
    ["refiner", "inpaint", "conflict", "truncated", "malformed", "unknown_label"],
)
def test_unknown_conflicting_or_malformed_candidates_fail_closed(world: World, case: str) -> None:
    peer = world.sdxl("peer.safetensors", payload=b"peer")
    path = world.folder / "candidate.safetensors"
    if case == "refiner":
        tensor_checkpoint(path, architecture="refiner")
    elif case == "inpaint":
        tensor_checkpoint(path, architecture="inpaint")
    elif case == "conflict":
        checkpoint(path, metadata={"ss_base_model_version": "sdxl_base", "modelspec.architecture": "sd_v1"})
    elif case == "truncated":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x10\x00\x00\x00\x00\x00\x00\x00{")
    elif case == "malformed":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff" * 64)
    else:
        checkpoint(path, metadata={"ss_base_model_version": "my_custom_label"})
    with pytest.raises(ValueError, match="Model 1:"):
        world.prepare({"candidate": path, "peer": peer})
    assert not world.cache.exists()


# -- mixed studies ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("exact", [ZIMAGE, KLEIN])
def test_sdxl_and_exact_profile_plan_from_one_source_on_cold_and_warm_caches(world: World, exact: str) -> None:
    files = {"standard": world.sdxl("standard.safetensors"), exact: world.opaque(exact)}
    plans = []
    for _ in range(2):  # cold, then warm (a fresh registry over the persisted cache)
        evidence, registry = world.prepare(files)
        exp = study(world.tmp_path, models=list(files))
        plans.append((build_comparison_snapshot(exp, shared_baseline(), evidence=evidence), registry))
    cold, warm = plans
    assert cold[1].last_refresh.hashes_computed == 1 and warm[1].last_refresh.hashes_computed == 0
    for snapshot, _ in plans:
        sdxl_arm, exact_arm = snapshot["model_comparison"]["arms"]
        assert sdxl_arm["source_intent_sha256"] == exact_arm["source_intent_sha256"]
        assert sdxl_arm["shared_geometry"] == exact_arm["shared_geometry"] == {"width": 1024, "height": 1024}
        assert exact_arm["model_policy_context"]["evidence"] == "exact_profile"
        assert exact_arm["checkpoint_evidence"]["authority"] == "exact_profile"
        assert exact_arm["effective_backend_options"]["image"]["model_profile"] is not None
        assert sdxl_arm["effective_config"]["txt2img"]["sampler_name"] != exact_arm["effective_config"]["txt2img"]["sampler_name"]
    first_arms = cold[0]["model_comparison"]["arms"]
    assert first_arms[0]["checkpoint_evidence"]["sha256"] == warm[0]["model_comparison"]["arms"][0]["checkpoint_evidence"]["sha256"]


def test_incompatible_shared_geometry_rejects_the_whole_study(world: World) -> None:
    files = {"standard": world.sdxl("standard.safetensors"), ZIMAGE: world.opaque(ZIMAGE)}
    evidence, _ = world.prepare(files)
    config = shared_baseline()
    config["txt2img"].update(width=768, height=1024)  # Z-Image qualifies only 1024x1024
    exp = study(world.tmp_path, models=list(files))
    with pytest.raises(ValueError, match="Shared geometry 768x1024 is not qualified for this candidate"):
        build_comparison_snapshot(exp, config, evidence=evidence)


def test_incompatible_backend_or_required_control_rejects_the_whole_study(world: World) -> None:
    files = {"standard": world.sdxl("standard.safetensors"), ZIMAGE: world.opaque(ZIMAGE)}
    evidence, _ = world.prepare(files)
    backend = shared_baseline()
    backend["backend_options"] = {"image": {"backend_id": "a1111_webui"}}
    with pytest.raises(ValueError, match="different configured image backend"):
        build_comparison_snapshot(study(world.tmp_path, models=list(files)), backend, evidence=evidence)
    hires = shared_baseline()
    hires["txt2img"]["enable_hr"] = True
    with pytest.raises(ValueError, match="cannot execute requested hires"):
        build_comparison_snapshot(study(world.tmp_path, models=list(files)), hires, evidence=evidence)


# -- frozen Run ------------------------------------------------------------------------------------------------------


def test_frozen_run_makes_no_registry_scan_hash_or_policy_lookup_and_admits_once(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = {"standard": world.sdxl("standard.safetensors"), ZIMAGE: world.opaque(ZIMAGE)}
    evidence, _ = world.prepare(files)
    exp = study(world.tmp_path, models=list(files))
    controller = LearningController(learning_state=LearningState())
    controller._get_baseline_config = lambda: copy.deepcopy(shared_baseline())
    controller._learning_lora_resolver = lambda name: KleinLoraDecision(
        name, KleinLoraStatus.COMPATIBLE, "fixture"
    )
    controller.build_plan(exp, comparison_evidence=evidence)  # Preview, with the real readiness evidence
    frozen = exp.execution_snapshot_json
    assert thaw_snapshot(frozen)["model_comparison"]["arms"][1]["checkpoint_evidence"]["authority"] == "exact_profile"

    # From here on the registry, the family lookup, adaptation and live cards are all unusable.
    for name in ("refresh", "cached_snapshot", "inspect_checkpoint", "checkpoint_status", "verified_sha256"):
        monkeypatch.setattr(AssetRegistry, name, lambda *a, _n=name, **k: pytest.fail(f"registry.{_n} at Run"))
    monkeypatch.setattr(
        "src.image_backends.model_policy.RegistryFamilyLookup.__call__",
        lambda *a, **k: pytest.fail("family lookup at Run"),
    )
    monkeypatch.setattr("src.pipeline.resolution_layer.adapt_pack_intent", lambda *a, **k: pytest.fail("adapt at Run"))
    controller._get_baseline_config = lambda: pytest.fail("live cards at Run")
    controller._learning_policy_resolver = lambda _: pytest.fail("live policy at Run")

    service = SimpleNamespace(submit_njrs=Mock(side_effect=lambda records, policy: [r.job_id for r in records]))
    controller.pipeline_controller = object()
    controller.execution_controller = LearningExecutionController(controller.learning_state, service)
    controller.run_plan()

    assert service.submit_njrs.call_count == 1  # one atomic admission for every arm
    records = service.submit_njrs.call_args.args[0]
    assert [r.base_model for r in records] == ["standard", ZIMAGE]
    assert exp.execution_snapshot_json == frozen
    standard, zimage = (r.workload.metadata["model_comparison"]["checkpoint_evidence"] for r in records)
    assert standard["authority"] == "asset_registry" and len(standard["sha256"]) == 64
    assert zimage == {"authority": "exact_profile", "profile_ref": ZP.reference()}


def test_a_refused_arm_admits_nothing_and_leaves_no_partial_plan(world: World) -> None:
    files = {"standard": world.sdxl("standard.safetensors"), ZIMAGE: world.opaque(ZIMAGE)}
    evidence, _ = world.prepare(files)
    exp = study(world.tmp_path, models=list(files))
    config = shared_baseline()
    config["txt2img"].update(width=768, height=1024)
    controller = LearningController(learning_state=LearningState())
    controller._get_baseline_config = lambda: copy.deepcopy(config)
    with pytest.raises(ValueError, match="not qualified for this candidate"):
        controller.build_plan(exp, comparison_evidence=evidence)
    assert not exp.execution_snapshot_json and not exp.values
    assert controller.learning_state.plan == []
