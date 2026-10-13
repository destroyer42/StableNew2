"""Forge ControlNet contract (PR-IMG-CNET-210): pure admission, wire unit, and the backend's pre-dispatch refusals.

No WebUI, GPU or network: the pipeline is a ``Mock`` and the ControlNet catalog is an in-memory reader.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.api.webui_runtime_identity import (
    A1111_WEBUI_IDENTITY,
    FORGE_WEBUI_IDENTITY,
    WebUIRuntimeIdentity,
)
from src.conditioning.openpose import OpenPoseSelection
from src.conditioning.openpose_library import CODE_CHANGED, CODE_MISSING, OpenPoseInputError
from src.conditioning.openpose_snapshot import FrozenOpenPose, freeze_selection
from src.image_backends import A1111WebUIImageBackend, ForgeWebUIImageBackend, ImageExecutionRequest
from src.image_backends import forge_controlnet as fc
from tests.conditioning.openpose_fixtures_210 import (
    make_library,
    png_bytes,
    write_controlnet_weights,
)

FORGE = WebUIRuntimeIdentity(FORGE_WEBUI_IDENTITY)
A1111 = WebUIRuntimeIdentity(A1111_WEBUI_IDENTITY)
MODEL = "xinsir_openpose_sdxl"
ADVERTISED = "xinsir_openpose_sdxl [a1b2c3d4]"
MODULES = ("none", "canny", "openpose_full")


def _frozen(tmp_path: Path, *, model: str = MODEL, **overrides) -> tuple[FrozenOpenPose, bytes]:
    data = png_bytes(128, 192)
    library = make_library(tmp_path / "webui", {"Standing/relaxed.png": data})
    selection = OpenPoseSelection(asset="Standing/relaxed.png", model=model, **overrides)
    return freeze_selection(selection, library=library, snapshot_root=tmp_path / "snap"), data


def _catalog(models=(ADVERTISED, "other_model"), modules=MODULES, version=3) -> fc.ControlNetCatalog:
    return fc.ControlNetCatalog(models=None if models is None else tuple(models),
                                modules=None if modules is None else tuple(modules), version=version)


# --- resolve_advertised_model -----------------------------------------------------------------------------------


def test_the_exact_advertised_spelling_is_what_gets_sent() -> None:
    assert fc.resolve_advertised_model(MODEL, [ADVERTISED, "x"]) == ADVERTISED
    assert fc.resolve_advertised_model(ADVERTISED, [ADVERTISED]) == ADVERTISED
    assert fc.resolve_advertised_model("XINSIR_OPENPOSE_SDXL.safetensors", [ADVERTISED]) == ADVERTISED


def test_a_missing_model_lists_what_forge_does_advertise() -> None:
    with pytest.raises(fc.OpenPoseDispatchError) as caught:
        fc.resolve_advertised_model("nope", ["a", "b"])

    assert caught.value.code == fc.CODE_MODEL_MISSING
    assert "a, b" in str(caught.value) and "models/ControlNet" in str(caught.value)


def test_an_ambiguous_model_is_never_resolved_by_picking_one() -> None:
    with pytest.raises(fc.OpenPoseDispatchError) as caught:
        fc.resolve_advertised_model("dup", ["dup [11111111]", "sub/dup [22222222]"])

    assert caught.value.code == fc.CODE_MODEL_AMBIGUOUS


# --- admission -------------------------------------------------------------------------------------------------


def test_admission_succeeds_with_a_substantiated_sdxl_model(tmp_path: Path) -> None:
    frozen, _data = _frozen(tmp_path)
    root = tmp_path / "ControlNet"
    write_controlnet_weights(root / f"{MODEL}.safetensors", "sdxl")

    admission = fc.admit_openpose(frozen, _catalog(), controlnet_root=root)

    assert admission.unit_model == ADVERTISED
    assert admission.evidence["model_sdxl"]["status"] == "sdxl"
    assert admission.evidence["module"] == "None" and admission.evidence["script"] == "ControlNet"
    assert str(tmp_path) not in json.dumps(admission.evidence)


def test_an_unverifiable_model_is_admitted_but_clearly_labelled_unverified(tmp_path: Path) -> None:
    frozen, _data = _frozen(tmp_path)

    admission = fc.admit_openpose(frozen, _catalog(), controlnet_root=tmp_path / "no-controlnet-folder")

    assert admission.evidence["model_sdxl"]["status"] == "unverified"


def test_a_header_proven_non_sdxl_model_is_refused(tmp_path: Path) -> None:
    frozen, _data = _frozen(tmp_path)
    root = tmp_path / "ControlNet"
    write_controlnet_weights(root / f"{MODEL}.safetensors", "sd15")

    with pytest.raises(fc.OpenPoseDispatchError) as caught:
        fc.admit_openpose(frozen, _catalog(), controlnet_root=root)

    assert caught.value.code == fc.CODE_SDXL_MISMATCH


@pytest.mark.parametrize(
    ("catalog", "code"),
    [
        (_catalog(models=None), fc.CODE_RUNTIME),
        (_catalog(modules=None), fc.CODE_RUNTIME),
        (_catalog(modules=("canny", "openpose_full")), fc.CODE_MODULE),
        (_catalog(models=("something_else",)), fc.CODE_MODEL_MISSING),
    ],
)
def test_runtime_gaps_refuse_with_a_stable_code(tmp_path: Path, catalog, code: str) -> None:
    frozen, _data = _frozen(tmp_path)

    with pytest.raises(fc.OpenPoseDispatchError) as caught:
        fc.admit_openpose(frozen, catalog, controlnet_root=None)

    assert caught.value.code == code


def test_the_none_module_is_matched_case_insensitively(tmp_path: Path) -> None:
    frozen, _data = _frozen(tmp_path)

    assert fc.admit_openpose(frozen, _catalog(modules=("None", "canny")), controlnet_root=None).unit_model == ADVERTISED


# --- wire --------------------------------------------------------------------------------------------------------


def _config(frozen: FrozenOpenPose, *, model: str | None = ADVERTISED) -> dict:
    config = {"controlnet_openpose": frozen.to_config()}
    if model is not None:
        config[fc.RUNTIME_KEY] = {"model": model}
    return config


def test_exactly_one_unit_with_the_verified_bytes_and_settings(tmp_path: Path) -> None:
    frozen, data = _frozen(tmp_path, weight=0.8, guidance_start=0.1, guidance_end=0.9, control_mode="Balanced")
    payload = {"prompt": "p", "steps": 20}

    wire, evidence = fc.apply_openpose_wire_unit(_config(frozen), payload)

    assert "alwayson_scripts" not in payload  # the caller's copy is never mutated
    units = wire["alwayson_scripts"]["ControlNet"]["args"]
    assert len(units) == 1
    unit = units[0]
    assert base64.b64decode(unit.pop("image")) == data
    assert unit == {
        "enabled": True, "module": "None", "model": ADVERTISED, "weight": 0.8, "guidance_start": 0.1,
        "guidance_end": 0.9, "control_mode": "Balanced", "resize_mode": "Resize and Fill", "pixel_perfect": False,
        "save_detected_map": False,
    }
    assert evidence is not None and evidence["image_sha256_sent"] == hashlib.sha256(data).hexdigest()
    assert evidence["units"] == 1
    assert base64.b64encode(data).decode("ascii")[:48] not in json.dumps(evidence)  # evidence is content-free


def test_other_script_entries_such_as_adetailer_are_preserved_untouched(tmp_path: Path) -> None:
    frozen, _data = _frozen(tmp_path)
    adetailer = {"args": [True, {"ad_model": "face_yolov8n.pt"}]}

    wire, _evidence = fc.apply_openpose_wire_unit(
        _config(frozen), {"prompt": "p", "alwayson_scripts": {"ADetailer": adetailer}}
    )

    assert wire["alwayson_scripts"]["ADetailer"] == adetailer
    assert set(wire["alwayson_scripts"]) == {"ADetailer", "ControlNet"}


def test_an_existing_controlnet_entry_is_never_overwritten(tmp_path: Path) -> None:
    frozen, _data = _frozen(tmp_path)

    with pytest.raises(fc.OpenPoseDispatchError) as caught:
        fc.apply_openpose_wire_unit(_config(frozen), {"alwayson_scripts": {"controlnet": {"args": []}}})

    assert caught.value.code == fc.CODE_CONFLICT


def test_unconditioned_requests_pass_through_unchanged() -> None:
    payload = {"prompt": "p"}

    wire, evidence = fc.apply_openpose_wire_unit({"width": 512}, payload)

    assert wire is payload and evidence is None


def test_a_request_that_was_never_admitted_is_refused(tmp_path: Path) -> None:
    frozen, _data = _frozen(tmp_path)

    with pytest.raises(fc.OpenPoseDispatchError) as caught:
        fc.apply_openpose_wire_unit(_config(frozen, model=None), {"prompt": "p"})

    assert caught.value.code == fc.CODE_UNADMITTED


def test_a_changed_or_deleted_snapshot_refuses_the_wire_step(tmp_path: Path) -> None:
    frozen, _data = _frozen(tmp_path)
    path = Path(frozen.snapshot_path)

    path.write_bytes(png_bytes(color=(5, 5, 5)))
    with pytest.raises(OpenPoseInputError) as changed:
        fc.apply_openpose_wire_unit(_config(frozen), {"prompt": "p"})
    assert changed.value.code == CODE_CHANGED

    path.unlink()
    with pytest.raises(OpenPoseInputError) as missing:
        fc.apply_openpose_wire_unit(_config(frozen), {"prompt": "p"})
    assert missing.value.code == CODE_MISSING


def test_an_altered_frozen_record_is_refused_not_trusted(tmp_path: Path) -> None:
    frozen, _data = _frozen(tmp_path)
    config = _config(frozen)
    config["controlnet_openpose"]["asset_sha256"] = "0" * 64  # no longer matches the snapshot name

    with pytest.raises(fc.OpenPoseDispatchError) as caught:
        fc.apply_openpose_wire_unit(config, {"prompt": "p"})

    assert caught.value.code == fc.CODE_RECORD


# --- intent validation -----------------------------------------------------------------------------------------


def test_intent_validation_refuses_unsupported_backends_and_missing_txt2img(tmp_path: Path) -> None:
    frozen, _data = _frozen(tmp_path)
    config = _config(frozen)

    assert fc.validate_openpose_intent({}, ("txt2img",), backend_id="forge_webui", backend_supported=True) is None
    with pytest.raises(fc.OpenPoseDispatchError) as backend:
        fc.validate_openpose_intent(config, ("txt2img",), backend_id="a1111_webui", backend_supported=False)
    assert backend.value.code == fc.CODE_BACKEND
    with pytest.raises(fc.OpenPoseDispatchError) as stage:
        fc.validate_openpose_intent(config, ("img2img",), backend_id="forge_webui", backend_supported=True)
    assert stage.value.code == fc.CODE_STAGE
    assert fc.validate_openpose_intent(
        config, ("txt2img", "adetailer"), backend_id="forge_webui", backend_supported=True
    ) == frozen


# --- the backends ------------------------------------------------------------------------------------------------


def _forge_client(catalog: dict | None, *, identity=FORGE) -> SimpleNamespace:
    state = {"writes": []}

    def _set(selection) -> bool:
        state["writes"].append(list(selection))
        return True

    return SimpleNamespace(
        probe_runtime_identity=lambda: identity,
        get_additional_modules=lambda: [],
        set_additional_modules=_set,
        get_controlnet_catalog=(lambda: catalog) if catalog is not None else None,
        state=state,
    )


def _ready() -> Mock:
    transition = Mock()
    transition.prepare_for.return_value = Mock(ready=True)
    return transition


def _request(tmp_path: Path, frozen: FrozenOpenPose, *, stage: str = "txt2img", **overrides) -> ImageExecutionRequest:
    values = {
        "backend_id": "forge_webui",
        "stage_name": stage,
        "stage_config": {"steps": 20},
        "output_dir": tmp_path / "out",
        "prompt": "a person",
        "selected_model": "juggernaut.safetensors",
        "steps": 20,
        "cfg_scale": 7.0,
        "width": 1024,
        "height": 1024,
        "seed": 7,
        "job_id": "job-1",
        "backend_options": {"image": {"backend_id": "forge_webui"}},
        "execution_config": {"controlnet_openpose": frozen.to_config(), "steps": 20},
    }
    values.update(overrides)
    return ImageExecutionRequest(**values)


def _pipeline(client) -> Mock:
    pipeline = Mock()
    pipeline.client = client
    pipeline.run_txt2img_stage.return_value = {"path": "x.png", "all_paths": ["x.png"]}
    return pipeline


def _good_catalog() -> dict:
    return {"models": [ADVERTISED], "modules": list(MODULES), "version": 3}


def test_forge_forwards_the_conditioning_and_the_advertised_model_to_the_executor(tmp_path: Path) -> None:
    frozen, _data = _frozen(tmp_path)
    root = tmp_path / "CN"
    write_controlnet_weights(root / f"{MODEL}.safetensors", "sdxl")
    pipeline = _pipeline(_forge_client(_good_catalog()))
    backend = ForgeWebUIImageBackend(transition=_ready(), controlnet_root=root)

    result = backend.execute(pipeline, _request(tmp_path, frozen))

    config = pipeline.run_txt2img_stage.call_args.args[2]
    assert config["controlnet_openpose"] == frozen.to_config()
    assert config[fc.RUNTIME_KEY] == {"model": ADVERTISED}
    assert result is not None
    evidence = result.backend_metadata["openpose_conditioning"]
    assert evidence["advertised_model"] == ADVERTISED and evidence["model_sdxl"]["status"] == "sdxl"
    assert backend._openpose == {}  # per-job scratch is always released


def test_unconditioned_forge_work_gains_no_keys(tmp_path: Path) -> None:
    frozen, _data = _frozen(tmp_path)
    pipeline = _pipeline(_forge_client(None))
    request = _request(tmp_path, frozen, execution_config={"steps": 20})

    ForgeWebUIImageBackend(transition=_ready()).execute(pipeline, request)

    config = pipeline.run_txt2img_stage.call_args.args[2]
    assert "controlnet_openpose" not in config and fc.RUNTIME_KEY not in config


@pytest.mark.parametrize(
    ("client", "needle"),
    [
        (_forge_client(None), "cannot read the ControlNet capability"),
        (_forge_client({"models": None, "modules": None, "version": None}), "ControlNet extension did not answer"),
        (_forge_client({"models": ["other"], "modules": list(MODULES)}), "does not list the ControlNet model"),
        (_forge_client({"models": [ADVERTISED], "modules": ["canny"]}), "'None' preprocessor"),
    ],
)
def test_runtime_refusals_happen_before_any_module_write_or_generation(tmp_path: Path, client, needle: str) -> None:
    frozen, _data = _frozen(tmp_path)
    pipeline = _pipeline(client)

    with pytest.raises(fc.OpenPoseDispatchError, match=needle):
        ForgeWebUIImageBackend(transition=_ready()).execute(pipeline, _request(tmp_path, frozen))

    pipeline.run_txt2img_stage.assert_not_called()
    assert client.state["writes"] == []


def test_a_changed_snapshot_refuses_before_forge_is_asked_anything_else(tmp_path: Path) -> None:
    frozen, _data = _frozen(tmp_path)
    Path(frozen.snapshot_path).write_bytes(b"tampered")
    catalog = Mock(return_value=_good_catalog())
    client = _forge_client(_good_catalog())
    client.get_controlnet_catalog = catalog
    pipeline = _pipeline(client)

    with pytest.raises(OpenPoseInputError):
        ForgeWebUIImageBackend(transition=_ready()).execute(pipeline, _request(tmp_path, frozen))

    catalog.assert_not_called()
    pipeline.run_txt2img_stage.assert_not_called()


def test_a1111_refuses_conditioning_before_touching_the_pipeline(tmp_path: Path) -> None:
    frozen, _data = _frozen(tmp_path)
    pipeline = _pipeline(_forge_client(_good_catalog(), identity=A1111))
    request = _request(tmp_path, frozen, backend_id="a1111_webui", backend_options={"image": {"backend_id": "a1111_webui"}})

    with pytest.raises(fc.OpenPoseDispatchError) as caught:
        A1111WebUIImageBackend(transition=_ready()).execute(pipeline, request)

    assert caught.value.code == fc.CODE_BACKEND
    pipeline.run_txt2img_stage.assert_not_called()


def test_a1111_njr_intent_is_refused_before_dispatch(tmp_path: Path) -> None:
    frozen, _data = _frozen(tmp_path)
    njr = SimpleNamespace(config={"controlnet_openpose": frozen.to_config()}, backend_options={}, base_model="x")

    with pytest.raises(fc.OpenPoseDispatchError):
        A1111WebUIImageBackend(transition=_ready()).validate_njr_intent(njr, ["txt2img"])
    A1111WebUIImageBackend(transition=_ready()).validate_njr_intent(
        SimpleNamespace(config={}, backend_options={}, base_model="x"), ["txt2img"]
    )  # unconditioned A1111 work is untouched


@pytest.mark.parametrize("model", ["flux-2-klein-4b-fp8.safetensors"])
def test_exact_profile_models_are_refused_by_the_forge_backend(tmp_path: Path, model: str) -> None:
    frozen, _data = _frozen(tmp_path)
    njr = SimpleNamespace(
        config={"controlnet_openpose": frozen.to_config()}, backend_options={}, base_model=model,
        extra_metadata={}, positive_prompt="p", lora_tags=(), input_image_paths=(), stage_chain=(),
    )

    with pytest.raises(fc.OpenPoseDispatchError):
        ForgeWebUIImageBackend(transition=_ready()).validate_njr_intent(njr, ["txt2img"])


def test_non_txt2img_stages_do_not_admit_or_carry_conditioning(tmp_path: Path) -> None:
    frozen, _data = _frozen(tmp_path)
    pipeline = _pipeline(_forge_client(_good_catalog()))
    pipeline.run_img2img_stage.return_value = {"path": "i.png"}
    request = _request(tmp_path, frozen, stage="img2img", input_image_path=tmp_path / "in.png")

    ForgeWebUIImageBackend(transition=_ready()).execute(pipeline, request)

    config = pipeline.run_img2img_stage.call_args.kwargs["config"]
    assert "controlnet_openpose" not in config and fc.RUNTIME_KEY not in config


def test_capabilities_state_the_contract() -> None:
    assert ForgeWebUIImageBackend.capabilities.supports_openpose_conditioning is True
    assert A1111WebUIImageBackend.capabilities.supports_openpose_conditioning is False
    assert "controlnet" not in ForgeWebUIImageBackend.capabilities.stage_types  # still not an image stage
