"""PR-IMG-FORGE-100: explicit, non-default ``forge_webui`` image backend (deterministic, no real I/O).

Covers durable identity, defaults, historical compatibility, replay lineage, registry/capability
policy, the runtime identity guard (before any generation dispatch), stage translation parity with
the A1111 adapter, and result normalization. No WebUI, GPU, model or user data is touched; the
transition coordinator is always injected.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.api.webui_runtime_identity import (
    A1111_WEBUI_IDENTITY,
    FORGE_WEBUI_IDENTITY,
    UNKNOWN_RUNTIME_IDENTITY,
    WebUIRuntimeIdentity,
    WebUIRuntimeIdentityMismatch,
)
from src.image_backends import (
    A1111_IMAGE_BACKEND_ID,
    FORGE_IMAGE_BACKEND_ID,
    LEGACY_MISSING_IMAGE_BACKEND_ID,
    NEW_IMAGE_BACKEND_DEFAULT_ID,
    A1111WebUIImageBackend,
    ForgeWebUIImageBackend,
    ImageBackendRegistry,
    ImageExecutionRequest,
    build_default_image_backend_registry,
    normalize_image_backend_options,
    resolve_image_backend_id,
)
from src.pipeline.cli_njr_builder import build_cli_njr
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot
from tests.helpers.njr_factory import make_pipeline_njr

FORGE = WebUIRuntimeIdentity(FORGE_WEBUI_IDENTITY)
A1111 = WebUIRuntimeIdentity(A1111_WEBUI_IDENTITY)


def _forge_client(probe, modules: list[str] | None = None) -> SimpleNamespace:
    """Forge-shaped client double: identity probe plus a persistent, verified module selection (D110)."""

    state = {"modules": list(modules or []), "writes": []}

    def _set(selection) -> bool:
        state["writes"].append(list(selection))
        state["modules"] = list(selection)
        return True

    return SimpleNamespace(
        probe_runtime_identity=probe,
        get_additional_modules=lambda: list(state["modules"]),
        set_additional_modules=_set,
        module_state=state,
    )


def _ready_transition() -> Mock:
    transition = Mock()
    transition.prepare_for.return_value = Mock(ready=True)
    return transition


def _runner(tmp_path: Path, observed: WebUIRuntimeIdentity | None, transitions: dict | None = None):
    """Runner with both WebUI-family backends and a stub pipeline bound to ``observed``."""

    transitions = transitions if transitions is not None else {}
    registry = ImageBackendRegistry()
    transitions.setdefault("a1111", _ready_transition())
    transitions.setdefault("forge", _ready_transition())
    registry.register(A1111WebUIImageBackend(transition=transitions["a1111"]))
    registry.register(ForgeWebUIImageBackend(transition=transitions["forge"]))
    runner = PipelineRunner(
        Mock(), Mock(), runs_base_dir=str(tmp_path / "out"), image_backend_registry=registry
    )
    pipeline = Mock()
    output = tmp_path / "txt2img.png"
    output.write_bytes(b"png")
    pipeline.run_txt2img_stage.return_value = {"path": str(output), "all_paths": [str(output)]}
    pipeline.client = _forge_client((lambda: observed) if observed is not None else None)
    runner._pipeline = pipeline
    return runner, pipeline


# --------------------------------------------------------------------------------------------
# 1-3, 5: durable identity, defaults, historical compatibility, registry
# --------------------------------------------------------------------------------------------


def test_forge_is_the_new_work_default_and_a1111_the_historical_compatibility_identity() -> None:
    assert FORGE_IMAGE_BACKEND_ID == NEW_IMAGE_BACKEND_DEFAULT_ID == "forge_webui"
    assert A1111_IMAGE_BACKEND_ID == LEGACY_MISSING_IMAGE_BACKEND_ID == "a1111_webui"
    assert ForgeWebUIImageBackend.backend_id == "forge_webui" and A1111WebUIImageBackend.backend_id == "a1111_webui"
    assert normalize_image_backend_options(None)["image"]["backend_id"] == "forge_webui"
    assert (
        normalize_image_backend_options({"image": {"backend_id": "forge_webui"}})["image"][
            "backend_id"
        ]
        == "forge_webui"
    )


def test_registry_contains_both_backends_and_historical_records_still_resolve_to_a1111() -> None:
    registry = build_default_image_backend_registry()
    assert registry.list_backend_ids() == ["a1111_webui", "forge_webui"]
    assert isinstance(registry.get("forge_webui"), ForgeWebUIImageBackend)
    assert resolve_image_backend_id({}) == "a1111_webui"
    assert resolve_image_backend_id(None) == "a1111_webui"
    assert resolve_image_backend_id({"image": {}}) == "a1111_webui"
    assert resolve_image_backend_id({"image": {"backend_id": "forge_webui"}}) == "forge_webui"


def test_new_image_work_defaults_to_forge_and_explicit_identities_survive_compilation() -> None:
    default_record = build_cli_njr(prompt="p", config={"txt2img": {}}, batch_size=1)
    assert default_record.backend_options["image"]["backend_id"] == "forge_webui"
    a1111_record = build_cli_njr(
        prompt="p",
        config={"txt2img": {}, "backend_options": {"image": {"backend_id": "a1111_webui"}}},
        batch_size=1,
    )
    assert a1111_record.backend_options["image"]["backend_id"] == "a1111_webui"  # an explicit identity is never rewritten
    forge_record = build_cli_njr(
        prompt="p",
        config={"txt2img": {}, "backend_options": {"image": {"backend_id": "forge_webui"}}},
        batch_size=1,
    )
    assert forge_record.backend_options["image"]["backend_id"] == "forge_webui"


def test_historical_njr_without_image_backend_never_resolves_to_forge() -> None:
    record = make_pipeline_njr()
    payload = record.to_dict()
    payload["workload"]["backend_options"] = {}
    restored = NormalizedJobRecord.from_dict(payload)
    assert resolve_image_backend_id(restored.backend_options) == "a1111_webui"


def test_explicit_forge_identity_survives_njr_serialization_and_queue_snapshot() -> None:
    record = make_pipeline_njr(backend_options={"image": {"backend_id": "forge_webui"}})
    restored = NormalizedJobRecord.from_dict(record.to_dict())
    assert restored.backend_options["image"]["backend_id"] == "forge_webui"
    snapshot = normalized_job_from_snapshot({"normalized_job": record.to_queue_snapshot()})
    assert snapshot is not None
    assert snapshot.backend_options["image"]["backend_id"] == "forge_webui"


def test_replay_preserves_forge_identity_and_creates_new_lineage() -> None:
    original = make_pipeline_njr(
        job_id="forge-parent", backend_options={"image": {"backend_id": "forge_webui"}}
    )
    replay = compile_replay_intent(
        ReplayIntent(record=original, parent_artifact_id="artifact-parent"),
        id_fn=lambda: "forge-replay",
    )
    assert replay.job_id == "forge-replay" != original.job_id
    assert replay.source.parent_job_id == "forge-parent"
    assert replay.backend_options["image"]["backend_id"] == "forge_webui"


# --------------------------------------------------------------------------------------------
# 6: capability policy
# --------------------------------------------------------------------------------------------


def test_forge_capabilities_are_exactly_the_four_still_image_stages_without_controlnet() -> None:
    caps = ForgeWebUIImageBackend.capabilities
    assert caps.backend_id == "forge_webui"
    assert set(caps.stage_types) == {"txt2img", "img2img", "adetailer", "upscale"}
    assert "controlnet" not in caps.stage_types


def test_unsupported_stage_chain_is_rejected_by_the_registry_before_dispatch() -> None:
    registry = build_default_image_backend_registry()
    registry.validate_stage_chain("forge_webui", ["txt2img", "adetailer", "upscale"])
    with pytest.raises(ValueError, match="does not support stage chain: controlnet"):
        registry.validate_stage_chain("forge_webui", ["txt2img", "controlnet"])


def test_forge_transition_target_is_forge_and_other_webui_identity_is_not_a1111() -> None:
    assert ForgeWebUIImageBackend.transition_target == "forge_webui"
    assert A1111WebUIImageBackend.transition_target == "a1111_webui"


# --------------------------------------------------------------------------------------------
# 7: runtime mismatch fails before any generation dispatch (runner path)
# --------------------------------------------------------------------------------------------


def _forge_njr():
    return make_pipeline_njr(backend_options={"image": {"backend_id": "forge_webui"}})


def _a1111_njr():
    return make_pipeline_njr(backend_options={"image": {"backend_id": "a1111_webui"}})


def _historical_njr():
    record = make_pipeline_njr()
    payload = record.to_dict()
    payload["workload"]["backend_options"] = {}
    return NormalizedJobRecord.from_dict(payload)


def test_a1111_njr_on_identified_a1111_is_allowed(tmp_path: Path) -> None:
    runner, pipeline = _runner(tmp_path, A1111)
    result = runner.run_njr(_a1111_njr())
    assert result.success is True
    pipeline.run_txt2img_stage.assert_called_once()
    assert result.metadata["image_backend_id"] == "a1111_webui"


def test_forge_njr_on_identified_forge_is_allowed_and_records_forge_identity(
    tmp_path: Path,
) -> None:
    transitions: dict = {}
    runner, pipeline = _runner(tmp_path, FORGE, transitions)
    result = runner.run_njr(_forge_njr())
    assert result.success is True
    pipeline.run_txt2img_stage.assert_called_once()
    assert result.metadata["image_backend_id"] == "forge_webui"
    transitions["forge"].prepare_for.assert_called_once_with("forge_webui")
    transitions["a1111"].prepare_for.assert_not_called()
    assert result.variants[0]["image_backend_id"] == "forge_webui"


@pytest.mark.parametrize(
    ("njr_factory", "observed"),
    [
        (_a1111_njr, FORGE),  # a1111 NJR + identified Forge
        (_forge_njr, A1111),  # forge NJR + identified A1111
        (_forge_njr, UNKNOWN_RUNTIME_IDENTITY),  # forge NJR + unidentified endpoint
        (_forge_njr, None),  # forge NJR + client with no probe at all
        (_historical_njr, FORGE),  # historical no-ID NJR resolves to a1111, then mismatch
    ],
)
def test_runtime_mismatch_fails_before_generation_dispatch(
    tmp_path: Path, njr_factory, observed: WebUIRuntimeIdentity | None
) -> None:
    runner, pipeline = _runner(tmp_path, observed)
    result = runner.run_njr(njr_factory())
    assert result.success is False
    assert "WebUI runtime identity mismatch" in str(result.error)
    pipeline.run_txt2img_stage.assert_not_called()
    pipeline.run_img2img_stage.assert_not_called()
    pipeline.run_adetailer_stage.assert_not_called()
    pipeline.run_upscale_stage.assert_not_called()


@pytest.mark.parametrize("observed", [A1111, UNKNOWN_RUNTIME_IDENTITY, None])
def test_a1111_and_historical_njr_unchanged_when_endpoint_is_not_forge(
    tmp_path: Path, observed: WebUIRuntimeIdentity | None
) -> None:
    for factory in (_a1111_njr, _historical_njr):
        runner, pipeline = _runner(tmp_path, observed)
        result = runner.run_njr(factory())
        assert result.success is True
        pipeline.run_txt2img_stage.assert_called_once()
        assert result.metadata["image_backend_id"] == "a1111_webui"


def test_direct_backend_guard_raises_the_typed_mismatch_error_before_calling_the_pipeline() -> None:
    pipeline = Mock()
    pipeline.client = SimpleNamespace(probe_runtime_identity=lambda: A1111)
    request = ImageExecutionRequest(
        backend_id="forge_webui",
        stage_name="txt2img",
        stage_config={},
        output_dir=Path("."),
        image_name="x",
        prompt="p",
    )
    with pytest.raises(WebUIRuntimeIdentityMismatch):
        ForgeWebUIImageBackend(transition=_ready_transition()).execute(pipeline, request)
    assert pipeline.method_calls == []


# --------------------------------------------------------------------------------------------
# 10-13, 17: stage translation parity (shared with A1111) and result normalization
# --------------------------------------------------------------------------------------------


def _request(stage_name: str, tmp_path: Path, backend_id: str) -> ImageExecutionRequest:
    input_path = tmp_path / "input.png" if stage_name != "txt2img" else None
    if input_path:
        input_path.write_bytes(b"input")
    return ImageExecutionRequest(
        backend_id=backend_id,
        stage_name=stage_name,
        stage_config={
            "denoising_strength": 0.35,
            "extra": {
                "prompt": "stage prompt",
                "negative_prompt": "stage negative",
                "upscaler": "R-ESRGAN 4x+",
                "adetailer_model": "face_yolov8n.pt",
            },
        },
        output_dir=tmp_path,
        input_image_path=input_path,
        image_name=stage_name,
        prompt="prompt",
        negative_prompt="negative",
        selected_model="known-good.safetensors",
        selected_vae="known-vae.safetensors",
        sampler="Euler a",
        scheduler="Karras",
        steps=24,
        cfg_scale=5.5,
        width=832,
        height=1216,
        seed=424242,
        image_count=2,
        execution_config={"enable_hr": True, "hr_scale": 1.5},
        cancel_token=object(),
    )


@pytest.mark.parametrize("stage_name", ["txt2img", "img2img", "adetailer", "upscale"])
def test_forge_delegates_each_stage_with_the_same_translation_as_a1111(
    stage_name: str, tmp_path: Path
) -> None:
    forge_pipeline, a1111_pipeline = Mock(), Mock()
    for pipeline, observed in (
        (forge_pipeline, FORGE),
        (a1111_pipeline, UNKNOWN_RUNTIME_IDENTITY),
    ):
        getattr(pipeline, f"run_{stage_name}_stage").return_value = {
            "path": str(tmp_path / f"{stage_name}.png")
        }
        pipeline.client = SimpleNamespace(probe_runtime_identity=lambda observed=observed: observed)
    # Forge additionally verifies its module baseline; A1111's client has no module API at all (D110).
    forge_pipeline.client = _forge_client(lambda: FORGE)
    forge_transition = _ready_transition()
    forge_request = _request(stage_name, tmp_path, "forge_webui")
    forge_result = ForgeWebUIImageBackend(transition=forge_transition).execute(
        forge_pipeline, forge_request
    )
    a1111_result = A1111WebUIImageBackend(transition=_ready_transition()).execute(
        a1111_pipeline, _request(stage_name, tmp_path, "a1111_webui")
    )

    forge_transition.prepare_for.assert_called_once_with("forge_webui")
    method_name = f"run_{stage_name}_stage"
    forge_call = getattr(forge_pipeline, method_name).call_args
    a1111_call = getattr(a1111_pipeline, method_name).call_args
    # Mechanically identical executor translation: only the backend identity differs.
    forge_args = {k: v for k, v in forge_call.kwargs.items() if k != "cancel_token"}
    a1111_args = {k: v for k, v in a1111_call.kwargs.items() if k != "cancel_token"}
    assert forge_args == a1111_args
    assert forge_call.args == a1111_call.args
    assert forge_call.kwargs["cancel_token"] is forge_request.cancel_token

    assert forge_result is not None and a1111_result is not None
    assert forge_result.backend_id == "forge_webui"
    assert forge_result.backend_metadata["backend_id"] == "forge_webui"
    payload = forge_result.to_variant_payload()
    assert payload["image_backend_id"] == "forge_webui"
    assert a1111_result.to_variant_payload()["image_backend_id"] == "a1111_webui"


def test_forge_txt2img_preserves_prompt_model_vae_sampler_scheduler_steps_cfg_geometry_seed(
    tmp_path: Path,
) -> None:
    pipeline = Mock()
    pipeline.run_txt2img_stage.return_value = {"path": str(tmp_path / "txt2img.png")}
    pipeline.client = _forge_client(lambda: FORGE)
    ForgeWebUIImageBackend(transition=_ready_transition()).execute(
        pipeline, _request("txt2img", tmp_path, "forge_webui")
    )
    prompt, negative, config, output_dir = pipeline.run_txt2img_stage.call_args.args
    assert (prompt, negative) == ("prompt", "negative")
    assert config["model"] == "known-good.safetensors"
    assert config["vae"] == "known-vae.safetensors"
    assert config["sampler_name"] == "Euler a"
    assert config["scheduler"] == "Karras"
    assert (config["steps"], config["cfg_scale"]) == (24, 5.5)
    assert (config["width"], config["height"]) == (832, 1216)
    assert config["seed"] == 424242
    assert output_dir == tmp_path


def test_forge_img2img_preserves_input_image_denoise_model_and_vae(tmp_path: Path) -> None:
    pipeline = Mock()
    pipeline.run_img2img_stage.return_value = {"path": str(tmp_path / "img2img.png")}
    pipeline.client = _forge_client(lambda: FORGE)
    request = _request("img2img", tmp_path, "forge_webui")
    ForgeWebUIImageBackend(transition=_ready_transition()).execute(pipeline, request)
    kwargs = pipeline.run_img2img_stage.call_args.kwargs
    assert kwargs["input_image_path"] == request.input_image_path
    config = kwargs["config"]
    assert config["denoising_strength"] == 0.35
    assert config["model"] == "known-good.safetensors"
    assert config["vae"] == "known-vae.safetensors"
    assert config["sd_vae"] == "known-vae.safetensors"


def test_forge_adetailer_and_upscale_keep_the_current_stage_contract(tmp_path: Path) -> None:
    pipeline = Mock()
    pipeline.run_adetailer_stage.return_value = {"path": str(tmp_path / "a.png")}
    pipeline.run_upscale_stage.return_value = {"path": str(tmp_path / "u.png")}
    pipeline.client = _forge_client(lambda: FORGE)
    backend = ForgeWebUIImageBackend(transition=_ready_transition())
    backend.execute(pipeline, _request("adetailer", tmp_path, "forge_webui"))
    config = pipeline.run_adetailer_stage.call_args.kwargs["config"]
    assert config["adetailer_enabled"] is True
    assert config["adetailer_prompt"] == "stage prompt"
    assert config["adetailer_negative_prompt"] == "stage negative"
    assert config["adetailer_model"] == "face_yolov8n.pt"
    backend.execute(pipeline, _request("upscale", tmp_path, "forge_webui"))
    assert pipeline.run_upscale_stage.call_args.kwargs["config"]["upscaler"] == "R-ESRGAN 4x+"


def test_forge_backend_rejects_unsupported_stage_name_without_touching_the_pipeline(
    tmp_path: Path,
) -> None:
    pipeline = Mock()
    pipeline.client = SimpleNamespace(probe_runtime_identity=lambda: FORGE)
    request = _request("txt2img", tmp_path, "forge_webui")
    request.stage_name = "controlnet"
    with pytest.raises(ValueError, match="forge_webui image backend does not support stage"):
        ForgeWebUIImageBackend(transition=_ready_transition()).execute(pipeline, request)
    assert pipeline.method_calls == []


def test_transition_failure_blocks_forge_before_identity_probe_or_generation(
    tmp_path: Path,
) -> None:
    from src.services.runtime_transition_service import RuntimeTransitionError

    blocked = Mock()
    blocked.prepare_for.return_value = Mock(
        ready=False, target="forge_webui", status=Mock(value="x"), blockers=("b",)
    )
    pipeline = Mock()
    probe = Mock()
    pipeline.client = SimpleNamespace(probe_runtime_identity=probe)
    with pytest.raises(RuntimeTransitionError):
        ForgeWebUIImageBackend(transition=blocked).execute(
            pipeline, _request("txt2img", tmp_path, "forge_webui")
        )
    probe.assert_not_called()
    pipeline.run_txt2img_stage.assert_not_called()


# --------------------------------------------------------------------------------------------
# PR-IMG-FORGE-D110: ordinary Forge work establishes its own module baseline before every stage
# --------------------------------------------------------------------------------------------

KLEIN_RESIDUE = ["flux2-vae.safetensors", "qwen_3_4b.safetensors"]


def _baseline_request(tmp_path: Path, vae: str | None, stage: str = "txt2img") -> ImageExecutionRequest:
    request = _request(stage, tmp_path, "forge_webui")
    request.selected_vae = vae
    return request


def _execute(tmp_path: Path, client, vae: str | None, stage: str = "txt2img"):
    pipeline = Mock()
    getattr(pipeline, f"run_{stage}_stage").return_value = {"path": str(tmp_path / f"{stage}.png")}
    pipeline.client = client
    result = ForgeWebUIImageBackend(transition=_ready_transition()).execute(
        pipeline, _baseline_request(tmp_path, vae, stage)
    )
    return pipeline, result


@pytest.mark.parametrize("vae", [None, "", "Automatic", "None"])
def test_automatic_vae_clears_klein_residue_before_the_stage_runs(tmp_path: Path, vae) -> None:
    client = _forge_client(lambda: FORGE, KLEIN_RESIDUE)
    pipeline, result = _execute(tmp_path, client, vae)
    assert client.module_state["writes"] == [[]] and client.module_state["modules"] == []
    pipeline.run_txt2img_stage.assert_called_once()
    assert result.backend_metadata["forge_module_baseline"]["applied"] is True


def test_explicit_vae_replaces_unrelated_residue_with_exactly_the_requested_vae(tmp_path: Path) -> None:
    client = _forge_client(lambda: FORGE, KLEIN_RESIDUE)
    _execute(tmp_path, client, "known-vae.safetensors")
    assert client.module_state["writes"] == [["known-vae.safetensors"]]


@pytest.mark.parametrize(
    ("current", "vae"),
    [([], None), ([], "known-vae.safetensors"), (["known-vae.safetensors"], "known-vae"), (["Known-VAE.safetensors"], "known-vae.safetensors")],
)
def test_matching_or_empty_state_is_never_written(tmp_path: Path, current: list[str], vae) -> None:
    client = _forge_client(lambda: FORGE, current)
    _, result = _execute(tmp_path, client, vae)
    assert client.module_state["writes"] == []
    assert result.backend_metadata["forge_module_baseline"]["applied"] is False


def test_unreadable_module_state_refuses_the_stage_before_it_runs(tmp_path: Path) -> None:
    from src.api.forge_client import ForgeVAEError

    client = _forge_client(lambda: FORGE, KLEIN_RESIDUE)
    client.get_additional_modules = lambda: None
    pipeline = Mock()
    pipeline.client = client
    with pytest.raises(ForgeVAEError, match="could not be read"):
        ForgeWebUIImageBackend(transition=_ready_transition()).execute(
            pipeline, _baseline_request(tmp_path, None)
        )
    pipeline.run_txt2img_stage.assert_not_called()
    assert client.module_state["writes"] == []


def test_a_client_without_the_module_api_refuses_rather_than_assuming_an_empty_state(tmp_path: Path) -> None:
    from src.api.forge_client import ForgeVAEError

    pipeline = Mock()
    pipeline.client = SimpleNamespace(probe_runtime_identity=lambda: FORGE)
    with pytest.raises(ForgeVAEError, match="cannot read and select"):
        ForgeWebUIImageBackend(transition=_ready_transition()).execute(
            pipeline, _baseline_request(tmp_path, None)
        )
    pipeline.run_txt2img_stage.assert_not_called()


def test_an_unverified_clear_refuses_the_stage(tmp_path: Path) -> None:
    from src.api.forge_client import ForgeVAEError

    client = _forge_client(lambda: FORGE, KLEIN_RESIDUE)
    client.set_additional_modules = lambda selection: True  # claims success, state does not change
    pipeline = Mock()
    pipeline.client = client
    with pytest.raises(ForgeVAEError, match="unverified module baseline"):
        ForgeWebUIImageBackend(transition=_ready_transition()).execute(
            pipeline, _baseline_request(tmp_path, None)
        )
    pipeline.run_txt2img_stage.assert_not_called()
