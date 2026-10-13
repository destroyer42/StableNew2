"""PR-IMG-CNET-210: PromptPack OpenPose conditioning compiles to immutable, verified, per-slot NJR intent.

Real ``PromptPackNormalizedJobBuilder`` + real native PromptPack files + real library/snapshot files in ``tmp_path``.
Only model-family evidence is injected (the persisted-snapshot contract); nothing scans, reaches a backend or a GPU.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
from src.conditioning.openpose import new_declaration
from src.conditioning.openpose_snapshot import FrozenOpenPose, verify_frozen
from src.gui.app_state_v2 import PackJobEntry
from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.njr_core_v26 import thaw_json
from src.pipeline.openpose_compile import OpenPoseCompileError, OpenPoseCompiler
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from src.promptpacks.storage import CURRENT_PROMPTPACK_SCHEMA_VERSION
from tests.conditioning.openpose_fixtures_210 import make_library, png_bytes
from tests.pipeline.test_prompt_pack_job_builder import (
    BASE_PACK_CONFIG,
    SequentialIdGenerator,
    StubConfigManager,
)

KLEIN = "flux-2-klein-4b-fp8.safetensors"
SDXL = "juggernaut.safetensors"
MYSTERY = "mystery.safetensors"
OLD = "sd15_model.safetensors"
_SDXL = CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ())
_SD1 = CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SD1, ())
CN_MODEL = "xinsir_openpose_sdxl"
POSE_A = new_declaration("Standing/relaxed.png", model=CN_MODEL)
POSE_B = {**new_declaration("Walking/forward.png", model=CN_MODEL), "weight": 0.6, "guidance_end": 0.8}
POSE_DISABLED = {**new_declaration("Sitting/seated.png", model=CN_MODEL), "enabled": False}


@pytest.fixture(autouse=True)
def _forge_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.image_backends.image_backend_types.configured_image_backend_id", lambda: "forge_webui")


def family_lookup(name: str):
    return {SDXL: _SDXL, OLD: _SD1, MYSTERY: None}.get(name)


class _Config(StubConfigManager):
    def __init__(self, tmp_path: Path, *, model: str) -> None:
        super().__init__(tmp_path)
        txt2img = {**BASE_PACK_CONFIG["txt2img"], "model": model, "negative_prompt": "config negative"}
        if model == KLEIN:
            txt2img.update(width=768, height=1024)
        if model == ZIMAGE_PROFILE_V1.transformer.filename:
            txt2img.update(width=1024, height=1024)
        self._config = {**BASE_PACK_CONFIG, "txt2img": txt2img}


def _slot(index: int, text: str, **extra: Any) -> dict[str, Any]:
    return {
        "index": index,
        "text": text,
        "negative": "",
        "positive_embeddings": [],
        "negative_embeddings": [],
        "loras": [],
        **extra,
    }


def _write_pack(tmp_path: Path, slots: list[dict[str, Any]], matrix: dict[str, Any] | None = None) -> None:
    path = tmp_path / "packs" / "pose-pack.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
                "pack_data": {
                    "name": "pose-pack",
                    "slots": slots,
                    "matrix": matrix or {"enabled": False, "mode": "fanout", "limit": 8, "slots": []},
                },
                "preset_data": {},
            }
        ),
        encoding="utf-8",
    )


class Harness:
    def __init__(self, tmp_path: Path, *, header_probe: Callable[[str], Any] | None = None) -> None:
        self.tmp_path = tmp_path
        self.library_files = {
            "Standing/relaxed.png": png_bytes(128, 192, (10, 20, 30)),
            "Walking/forward.png": png_bytes(160, 224, (40, 50, 60)),
            "Sitting/seated.png": png_bytes(96, 96, (70, 80, 90)),
        }
        self.library = make_library(tmp_path / "webui", self.library_files)
        self.compiler = OpenPoseCompiler(
            webui_root=tmp_path / "webui",
            snapshot_root=tmp_path / "snapshots",
            header_probe=header_probe or (lambda _name: None),
        )

    def build(
        self,
        slots: list[dict[str, Any]],
        *,
        model: str = SDXL,
        rows: list[int] | None = None,
        matrix: dict[str, Any] | None = None,
    ) -> list[NormalizedJobRecord]:
        config = _Config(self.tmp_path, model=model)
        _write_pack(self.tmp_path, slots, matrix)
        builder = PromptPackNormalizedJobBuilder(
            config_manager=config,
            job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
            packs_dir=config.packs_dir,
            model_family_lookup=family_lookup,
            openpose_compiler=self.compiler,
        )
        entries = [
            PackJobEntry(
                pack_id="pose-pack",
                pack_name="Pose Pack",
                config_snapshot={},
                stage_flags={"txt2img": True},
                randomizer_metadata={"enabled": False},
                pack_row_index=row,
                matrix_slot_values={},
            )
            for row in (rows if rows is not None else range(len(slots)))
        ]
        return builder.build_jobs(entries)


def frozen(record: NormalizedJobRecord) -> FrozenOpenPose | None:
    raw = record.config.get("controlnet_openpose")
    return FrozenOpenPose.from_config(raw) if raw is not None else None


# --- the owner outcome ---------------------------------------------------------------------------------------------


def test_a_slot_with_a_pose_freezes_verified_conditioning_into_the_njr(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    record = harness.build([_slot(0, "a person standing", controlnet_openpose=POSE_A)])[0]

    pose = frozen(record)

    assert pose is not None
    assert (pose.asset, pose.model, pose.weight) == ("Standing/relaxed.png", CN_MODEL, 1.0)
    assert (pose.guidance_start, pose.guidance_end, pose.control_mode) == (0.0, 1.0, "Balanced")
    assert (pose.resize_mode, pose.preprocessor, pose.pixel_perfect) == ("Resize and Fill", "None", False)
    assert verify_frozen(pose) == harness.library_files["Standing/relaxed.png"]  # the exact verified bytes
    assert record.config["controlnet_openpose"]["snapshot"] == {"path": pose.snapshot_path}


def test_the_njr_carries_no_image_bytes(tmp_path: Path) -> None:
    import base64

    harness = Harness(tmp_path)
    record = harness.build([_slot(0, "a person", controlnet_openpose=POSE_A)])[0]

    serialized = json.dumps(record.to_dict(), default=str)
    encoded = base64.b64encode(harness.library_files["Standing/relaxed.png"]).decode("ascii")

    assert encoded[:48] not in serialized
    assert "controlnet_openpose" in serialized


def test_provenance_records_why_the_target_was_admitted_without_content(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    record = harness.build([_slot(0, "a person", controlnet_openpose=POSE_A)])[0]

    conditioning = thaw_json(record.provenance.metadata["conditioning"]["controlnet_openpose"])

    assert conditioning["asset"] == "Standing/relaxed.png" and conditioning["model"] == CN_MODEL
    assert conditioning["target"] == {
        "family": "sdxl", "family_source": "registry_snapshot", "backend_id": "forge_webui", "stage": "txt2img",
    }
    assert "snapshot" not in conditioning and str(tmp_path) not in json.dumps(conditioning)


def test_jobs_without_conditioning_are_unchanged(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    record = harness.build([_slot(0, "a plain portrait")])[0]

    assert "controlnet_openpose" not in record.config
    assert "conditioning" not in record.provenance.metadata
    assert not (tmp_path / "snapshots").exists()


def test_a_mixed_pack_gives_each_slot_its_own_independent_intent(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    records = harness.build(
        [
            _slot(0, "standing person", controlnet_openpose=POSE_A),
            _slot(1, "walking person", controlnet_openpose=POSE_B),
            _slot(2, "seated person", controlnet_openpose=POSE_DISABLED),
        ]
    )

    first, second, third = (frozen(record) for record in records)

    assert first is not None and second is not None and third is None
    assert (first.asset, first.weight, first.guidance_end) == ("Standing/relaxed.png", 1.0, 1.0)
    assert (second.asset, second.weight, second.guidance_end) == ("Walking/forward.png", 0.6, 0.8)
    assert first.asset_sha256 != second.asset_sha256 and first.snapshot_path != second.snapshot_path
    assert "controlnet_openpose" not in records[2].config  # disabled: absent, not "disabled" intent
    assert [r.positive_prompt for r in records] == [
        records[0].positive_prompt, records[1].positive_prompt, records[2].positive_prompt
    ]


def test_row_index_selection_pairs_conditioning_with_the_rendered_row_not_the_slot_position(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    slots = [
        _slot(0, "first", controlnet_openpose=POSE_A),
        _slot(1, ""),  # empty padding does not produce a row
        _slot(2, "third", controlnet_openpose=POSE_B),
    ]

    only_second_row = harness.build(slots, rows=[1])

    assert len(only_second_row) == 1
    assert frozen(only_second_row[0]).asset == "Walking/forward.png"


def test_matrix_variants_each_receive_the_slots_conditioning_and_share_one_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.pipeline.openpose_compile as compile_module

    reads: list[str] = []
    real = compile_module.read_library_image

    def counting(root, identity):
        reads.append(identity)
        return real(root, identity)

    monkeypatch.setattr(compile_module, "read_library_image", counting)
    harness = Harness(tmp_path)
    matrix = {"enabled": True, "mode": "sequential", "limit": 8, "slots": [{"name": "env", "values": ["forest", "castle", "beach"]}]}

    records = harness.build([_slot(0, "a person in [[env]]", controlnet_openpose=POSE_A)], matrix=matrix)

    assert len(records) == 3
    assert {frozen(record).asset_sha256 for record in records} == {frozen(records[0]).asset_sha256}
    assert reads == ["Standing/relaxed.png"]  # one read for three variants


def test_a_disabled_declaration_needs_no_library_and_is_ignored(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    harness.compiler = OpenPoseCompiler(webui_root=None, snapshot_root=tmp_path / "s", header_probe=lambda _n: None)
    record = harness.build([_slot(0, "a person", controlnet_openpose=POSE_DISABLED)], model=KLEIN)[0]  # even on Klein

    assert "controlnet_openpose" not in record.config


# --- unsupported targets never silently drop conditioning ----------------------------------------------------------


@pytest.mark.parametrize("model", [KLEIN, ZIMAGE_PROFILE_V1.transformer.filename])
def test_exact_profile_targets_are_refused_at_compile(tmp_path: Path, model: str) -> None:
    harness = Harness(tmp_path)

    with pytest.raises(OpenPoseCompileError) as caught:
        harness.build([_slot(0, "a person", controlnet_openpose=POSE_A)], model=model)

    assert "does not support ControlNet" in str(caught.value) and "row 1" in str(caught.value)


def test_a1111_is_refused_at_compile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.image_backends.image_backend_types.configured_image_backend_id", lambda: "a1111_webui")
    harness = Harness(tmp_path)

    with pytest.raises(OpenPoseCompileError, match="only on the Forge WebUI backend"):
        harness.build([_slot(0, "a person", controlnet_openpose=POSE_A)])


def test_an_identified_non_sdxl_checkpoint_is_refused(tmp_path: Path) -> None:
    harness = Harness(tmp_path)

    with pytest.raises(OpenPoseCompileError, match="SDXL-only"):
        harness.build([_slot(0, "a person", controlnet_openpose=POSE_A)], model=OLD)


def test_an_unidentified_checkpoint_is_refused_unless_the_header_proves_sdxl(tmp_path: Path) -> None:
    refused = Harness(tmp_path / "a")
    with pytest.raises(OpenPoseCompileError, match="not identified this checkpoint as SDXL"):
        refused.build([_slot(0, "a person", controlnet_openpose=POSE_A)], model=MYSTERY)

    probed: list[str] = []

    def header(name: str):
        probed.append(name)
        return _SDXL

    proven = Harness(tmp_path / "b", header_probe=header)
    record = proven.build([_slot(0, "a person", controlnet_openpose=POSE_A)], model=MYSTERY)[0]

    assert probed == [MYSTERY]
    assert thaw_json(record.provenance.metadata["conditioning"]["controlnet_openpose"])["target"][
        "family_source"
    ] == "checkpoint_header"


def test_header_evidence_that_is_not_sdxl_does_not_upgrade_an_unverified_target(tmp_path: Path) -> None:
    harness = Harness(tmp_path, header_probe=lambda _name: _SD1)

    with pytest.raises(OpenPoseCompileError):
        harness.build([_slot(0, "a person", controlnet_openpose=POSE_A)], model=MYSTERY)


# --- input integrity ----------------------------------------------------------------------------------------------


def test_each_defect_aborts_the_whole_build_with_an_actionable_message(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    good = _slot(0, "ok", controlnet_openpose=POSE_A)

    cases = {
        "model": _slot(1, "x", controlnet_openpose={**POSE_B, "model": ""}),
        "missing": _slot(1, "x", controlnet_openpose=new_declaration("Standing/gone.png", model=CN_MODEL)),
        "invalid": _slot(1, "x", controlnet_openpose={**POSE_B, "weight": 9}),
        "malformed": _slot(1, "x", controlnet_openpose="not-an-object"),
    }
    for name, slot in cases.items():
        with pytest.raises(OpenPoseCompileError) as caught:
            harness.build([good, slot])
        assert "row 2" in str(caught.value), name  # names the offending slot


def test_a_hand_edited_traversal_identity_is_refused(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    (tmp_path / "secret.png").write_bytes(png_bytes())
    declaration = {**POSE_A, "asset": "../../secret.png"}

    with pytest.raises(OpenPoseCompileError):
        harness.build([_slot(0, "x", controlnet_openpose=declaration)])


def test_a_malformed_or_oversized_image_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(tmp_path)
    (harness.library / "Standing" / "relaxed.png").write_bytes(b"not an image")

    with pytest.raises(OpenPoseCompileError, match="not a readable image|corrupt"):
        harness.build([_slot(0, "x", controlnet_openpose=POSE_A)])

    (harness.library / "Standing" / "relaxed.png").write_bytes(png_bytes())
    import src.conditioning.openpose_library as library_module

    monkeypatch.setattr(library_module, "MAX_FILE_BYTES", 100)
    with pytest.raises(OpenPoseCompileError, match="larger than"):
        Harness(tmp_path / "again").build([_slot(0, "x", controlnet_openpose=POSE_A)])


def test_a_same_name_replacement_between_builds_cannot_alter_the_first_job(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    first = harness.build([_slot(0, "x", controlnet_openpose=POSE_A)])[0]
    original = harness.library_files["Standing/relaxed.png"]

    (harness.library / "Standing" / "relaxed.png").write_bytes(png_bytes(128, 192, (250, 1, 1)))
    # The same long-lived compiler (the controller caches the builder) must not serve the first build's bytes.
    second = harness.build([_slot(0, "x", controlnet_openpose=POSE_A)])[0]

    assert verify_frozen(frozen(first)) == original
    assert frozen(first).asset_sha256 != frozen(second).asset_sha256
    assert frozen(second).asset == frozen(first).asset  # same name, different (frozen) identity
