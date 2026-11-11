"""ADetailer modes resolve once from fully rendered image intent."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.controller.pipeline_controller import PipelineController
from src.gui.app_state_v2 import AppStateV2, PackJobEntry
from src.gui_v2.effective_settings import project_effective_settings
from src.image_backends.forge_klein_profile import KleinProfileError
from src.image_backends.forge_webui_backend import ForgeWebUIImageBackend
from src.pipeline.adetailer_profiles import compile_adetailer
from src.pipeline.cli_njr_builder import build_cli_njr
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.njr_core_v26 import NormalizedJobRecord
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.prompting.prompt_intent_analyzer import classify_subject_count
from src.utils.config import ADETAILER_DEFAULT_KEY, ConfigManager
from tests.pipeline.test_prompt_pack_job_builder import _write_native_pack


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("two people", "multiple"),
        ("three women", "multiple"),
        ("a couple posing together", "multiple"),
        ("family portrait", "multiple"),
        ("group photo of five friends", "multiple"),
        ("a crowd of people", "multiple"),
        ("two men and a woman", "multiple"),
        ("4 women", "multiple"),
        ("1girl, cinematic", "single"),
        ("single woman portrait", "single"),
        ("one man standing in a group of trees", "single"),
        ("one person in front of several statues", "single"),
        ("a group of buildings", "unknown"),
        ("group photo of five buildings", "unknown"),
        ("no people", "unknown"),
        ("no multiple faces", "unknown"),
        ("one person, two women", "unknown"),
        ("mannequin, Roman architecture <lora:two people:1> embedding:3girls", "unknown"),
    ],
)
def test_subject_count_uses_explicit_human_cues(prompt: str, expected: str) -> None:
    result = classify_subject_count(prompt)
    assert result.classification == expected
    assert result.version == 1 and result.reason


def _manager(tmp_path: Path) -> ConfigManager:
    manager = ConfigManager(
        presets_dir=tmp_path / "presets",
        packs_dir=tmp_path / "packs",
        global_prompt_dir=tmp_path / "prompts",
    )
    manager.packs_dir.mkdir(exist_ok=True)
    return manager


def _auto() -> dict:
    return {
        "face_mode": "auto",
        "enable_face_pass": True,
        "enable_hands_pass": True,
        "face_mode_profiles": {
            "single": {
                "adetailer_prompt": "",
                "adetailer_negative_prompt": "  ",
                "ad_hands_mask_k": 4,
            },
            "multiple": {
                "adetailer_prompt": "  détails\n<lora:portrait:0.5>\n",
                "adetailer_hands_prompt": "embedding:mãos",
                "ad_hands_mask_k": 0,
            },
        },
    }


def test_mixed_pack_matrix_preview_queue_and_replay_use_frozen_stage_values(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    path = _write_native_pack(
        manager.packs_dir / "mixed.json",
        text="single woman portrait",
        matrix={
            "enabled": True,
            "mode": "fanout",
            "limit": 4,
            "slots": [{"name": "subjects", "values": ["one woman", "three women"]}],
        },
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    document["pack_data"]["slots"][0]["negative"] = "avoid multiple faces, two people"
    document["pack_data"]["slots"].append({"index": 1, "text": "[[subjects]] on a beach"})
    document["preset_data"] = {
        "adetailer": _auto(),
        "pipeline": {"adetailer_enabled": True},
        "prompt_optimizer": {"enabled": False},
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    app_state = AppStateV2()
    controller = PipelineController(app_state=app_state, config_manager=manager)
    app_state.job_draft.packs = [
        PackJobEntry(
            pack_id=path.name,
            config_snapshot={},
            pack_name="Mixed",
            pack_row_index=row,
            stage_flags={"txt2img": True, "adetailer": True},
            randomizer_metadata={"enabled": False},
        )
        for row in (0, 1)
    ]
    controller.refresh_preview_from_state()
    jobs = list(app_state.preview_jobs)
    assert [job.provenance.metadata["adetailer_mode"]["effective_mode"] for job in jobs] == [
        "single",
        "single",
        "single",
        "multiple",
    ]
    view = project_effective_settings(jobs)
    assert "Auto → Single Face" in view.value_of("ADetailer")
    assert "Auto → Multiple Faces" in view.value_of("ADetailer")
    for job, mask_limit in zip(jobs, (1, 1, 1, 0), strict=True):
        adetailer = next(stage for stage in job.stages if stage.stage_type == "adetailer")
        assert adetailer.extra["ad_mask_k_largest"] == mask_limit
        assert adetailer.extra["ad_mask_merge_invert"] == "None"
        assert "face_mode_profiles" not in adetailer.extra
        assert "face_mode_profiles" not in job.config["adetailer"]
        assert adetailer.extra["adetailer_prompt"] == (
            "" if mask_limit else "  détails\n<lora:portrait:0.5>\n"
        )
        assert job.config["prompt_optimizer"]["enabled"] is False

    submit = Mock(return_value=len(jobs))
    monkeypatch.setattr(controller, "_submit_normalized_jobs", submit)
    assert controller.submit_preview_jobs_to_queue() == len(jobs)
    assert [job.to_queue_snapshot() for job in submit.call_args.args[0]] == [
        job.to_queue_snapshot() for job in jobs
    ]

    snapshot = NormalizedJobRecord.from_dict(jobs[-1].to_queue_snapshot())
    monkeypatch.setattr(
        "src.pipeline.adetailer_profiles.classify_subject_count", Mock(side_effect=AssertionError)
    )
    replay = compile_replay_intent(ReplayIntent(snapshot), id_fn=lambda: "adetailer-replay")
    assert replay.source.parent_job_id == snapshot.job_id
    assert replay.stages == snapshot.stages
    assert (
        replay.provenance.metadata["adetailer_mode"]
        == snapshot.provenance.metadata["adetailer_mode"]
    )


def test_application_default_is_for_fresh_work_and_pack_and_runtime_keep_their_scope(tmp_path):
    manager = _manager(tmp_path)
    assert manager.resolve_config()["adetailer"]["face_mode"] == "single"
    assert manager.update_settings({ADETAILER_DEFAULT_KEY: _auto()})
    assert _manager(tmp_path).resolve_config()["adetailer"]["face_mode"] == "auto"

    path = _write_native_pack(manager.packs_dir / "legacy.json", text="three women")
    manager.update_pack_config(
        path.name,
        {
            "adetailer": {
                "ad_mask_k_largest": 7,
                "ad_prompt": " legacy ",
                "enable_face_pass": False,
                "enable_hands_pass": True,
            }
        },
    )
    pack = manager.load_pack_config(path.name)
    legacy = manager.resolve_config(pack_overrides=pack)
    unchanged, evidence = compile_adetailer(legacy, "three women")
    assert unchanged is legacy and not evidence
    assert legacy["adetailer"]["ad_mask_k_largest"] == 7
    assert legacy["adetailer"]["adetailer_prompt"] == " legacy "
    assert not legacy["adetailer"]["enable_face_pass"]
    assert legacy["adetailer"]["enable_hands_pass"]

    override = manager.resolve_config(
        pack_overrides=pack,
        runtime_params={"adetailer": {"face_mode": "single", "ad_prompt": ""}},
    )
    compiled, decision = compile_adetailer(override, "three women")
    assert decision["effective_mode"] == "single" and decision["classification"] == "manual"
    assert compiled["adetailer"]["ad_mask_k_largest"] == 1
    assert compiled["adetailer"]["adetailer_prompt"] == ""


def test_generic_and_cli_compile_explicit_modes_without_changing_stage_flags(tmp_path):
    manager = _manager(tmp_path)
    config = manager.resolve_config(
        runtime_params={
            "prompt": "landscape",
            "pipeline": {"adetailer_enabled": True},
            "adetailer": _auto(),
        }
    )
    [generic] = JobBuilderV2().build_jobs(base_config=config)
    assert generic.provenance.metadata["adetailer_mode"]["uncertain"]
    assert generic.stages[-1].extra["ad_mask_k_largest"] == 1

    cli = build_cli_njr(prompt="a crowd of people", config=config, batch_size=1)
    assert cli.provenance.metadata["adetailer_mode"]["effective_mode"] == "multiple"
    assert cli.stages[-1].extra["ad_mask_k_largest"] == 0

    config["pipeline"]["adetailer_enabled"] = False
    [disabled] = JobBuilderV2().build_jobs(base_config=config)
    assert [stage.stage_type for stage in disabled.stages] == ["txt2img"]
    assert [
        stage.stage_type
        for stage in build_cli_njr(
            prompt="a crowd of people",
            config=config,
            batch_size=1,
        ).stages
    ] == ["txt2img"]


def test_auto_does_not_override_exact_model_refusal(tmp_path):
    config = _manager(tmp_path).resolve_config(
        runtime_params={
            "pipeline": {"adetailer_enabled": True},
            "txt2img": {"model": "flux-2-klein-4b-fp8.safetensors"},
            "adetailer": _auto(),
        }
    )
    record = build_cli_njr(prompt="three women", config=config, batch_size=1)
    stages = [stage.stage_type for stage in record.stages if stage.enabled]
    assert "adetailer" in stages
    with pytest.raises(KleinProfileError, match="adetailer"):
        ForgeWebUIImageBackend().validate_njr_intent(record, stages)
