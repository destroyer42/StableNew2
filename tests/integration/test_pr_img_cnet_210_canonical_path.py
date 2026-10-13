"""PR-IMG-CNET-210: PromptPack OpenPose conditioning through the canonical path (fakes only).

``PromptPack -> compiler -> immutable NJR -> JobService -> SQLite -> PipelineRunner.run_njr -> ForgeWebUIImageBackend ->
executor -> ForgeWebUIClient``. Only ``requests.Session.request`` is replaced (``FakeWebUITransport``), so no WebUI,
model or GPU is used. This proves the wire contract and lifecycle; it does **not** prove that a real Forge applies the
pose (that is the separately authorized physical check).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from src.api.forge_client import ForgeWebUIClient
from src.conditioning.openpose_snapshot import FrozenOpenPose
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.queue.job_model import JobStatus
from tests.conditioning.openpose_fixtures_210 import write_controlnet_weights
from tests.helpers.fake_webui_transport import FakeWebUITransport
from tests.helpers.njr_queue_harness import run_njr_via_queue
from tests.pipeline.test_openpose_compile_210 import (
    CN_MODEL,
    POSE_A,
    POSE_B,
    POSE_DISABLED,
    SDXL,
    Harness,
    _slot,
)

ADVERTISED = f"{CN_MODEL} [a1b2c3d4]"
MODULES = ["none", "canny", "openpose_full"]


@pytest.fixture(autouse=True)
def _forge_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.image_backends.image_backend_types.configured_image_backend_id", lambda: "forge_webui")


@pytest.fixture
def webui(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    harness = Harness(tmp_path)
    write_controlnet_weights(tmp_path / "webui" / "models" / "ControlNet" / f"{CN_MODEL}.safetensors", "sdxl")
    monkeypatch.setenv("STABLENEW_WEBUI_ROOT", str(tmp_path / "webui"))
    return harness


def _client(transport: FakeWebUITransport) -> ForgeWebUIClient:
    client = ForgeWebUIClient(base_url="http://127.0.0.1:7861", options_write_enabled=True)
    client._session.request = transport  # type: ignore[method-assign]
    client._options_min_interval_seconds = 0.0
    return client


def _transport(
    *, models: list[str] | None = None, modules: list[str] | None = None, detect_maps: bool = True
) -> FakeWebUITransport:
    return FakeWebUITransport(
        flavor="forge",
        checkpoint=SDXL,
        controlnet_models=[ADVERTISED, "other_model"] if models is None else models,
        controlnet_modules=MODULES if modules is None else modules,
        # Real Forge returns the generated image first and each unit's detect map after it (PR-IMG-CNET-210 physical check).
        append_controlnet_detect_maps=detect_maps,
    )


def _run(njr: NormalizedJobRecord, transport: FakeWebUITransport, tmp_path: Path, name: str = "run"):
    return run_njr_via_queue(njr, _client(transport), timeout_seconds=60.0, artifact_root=tmp_path / name)


def _variants(entry) -> list[dict[str, Any]]:
    return list((entry.result or {}).get("variants") or [])


def _unit(transport: FakeWebUITransport, index: int = 0) -> dict[str, Any]:
    payload = transport.payloads["/sdapi/v1/txt2img"][index]
    args = payload["alwayson_scripts"]["ControlNet"]["args"]
    assert len(args) == 1
    return args[0]


# --- the owner outcome ---------------------------------------------------------------------------------------------


def test_a_promptpack_pose_reaches_forge_as_exactly_one_verified_unit(webui: Harness, tmp_path: Path) -> None:
    njr = webui.build([_slot(0, "a person standing", controlnet_openpose=POSE_A)])[0]
    transport = _transport()

    entry = _run(njr, transport, tmp_path)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    assert [path for _, path, _ in transport.generation_calls] == ["/sdapi/v1/txt2img"]
    unit = _unit(transport)
    assert base64.b64decode(unit["image"]) == webui.library_files["Standing/relaxed.png"]
    assert {k: v for k, v in unit.items() if k != "image"} == {
        "enabled": True, "module": "None", "model": ADVERTISED, "weight": 1.0, "guidance_start": 0.0,
        "guidance_end": 1.0, "control_mode": "Balanced", "resize_mode": "Resize and Fill", "pixel_perfect": False,
    }
    payload = transport.payloads["/sdapi/v1/txt2img"][0]
    assert set(payload["alwayson_scripts"]) == {"ControlNet"}
    assert payload["prompt"].startswith("a person standing")  # the pose is conditioning, never appended prompt text


def test_provenance_survives_into_the_result_and_no_image_bytes_are_persisted(webui: Harness, tmp_path: Path) -> None:
    njr = webui.build([_slot(0, "a person", controlnet_openpose=POSE_A)])[0]
    transport = _transport()

    entry = _run(njr, transport, tmp_path)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    variant = _variants(entry)[0]
    sent = variant["controlnet_openpose"]
    assert sent["asset"] == "Standing/relaxed.png" and sent["units"] == 1 and sent["unit_model"] == ADVERTISED
    assert sent["image_sha256_sent"] == FrozenOpenPose.from_config(njr.config["controlnet_openpose"]).asset_sha256
    backend = variant["image_backend_metadata"]["openpose_conditioning"]
    assert backend["advertised_model"] == ADVERTISED and backend["model_sdxl"]["status"] == "sdxl"
    encoded = base64.b64encode(webui.library_files["Standing/relaxed.png"]).decode("ascii")[:64]
    assert encoded not in json.dumps(entry.result, default=str)
    for artifact in (tmp_path / "run").rglob("*.json"):  # manifests, run metadata
        assert encoded not in artifact.read_text(encoding="utf-8", errors="ignore"), artifact.name


def test_a_mixed_pack_dispatches_each_slots_own_intent(webui: Harness, tmp_path: Path) -> None:
    records = webui.build(
        [
            _slot(0, "standing person", controlnet_openpose=POSE_A),
            _slot(1, "walking person", controlnet_openpose=POSE_B),
            _slot(2, "seated person", controlnet_openpose=POSE_DISABLED),
        ]
    )
    transport = _transport()

    entries = [_run(record, transport, tmp_path, f"run{index}") for index, record in enumerate(records)]

    assert [entry.status for entry in entries] == [JobStatus.COMPLETED] * 3
    posts = transport.payloads["/sdapi/v1/txt2img"]
    assert len(posts) == 3
    first, second = _unit(transport, 0), _unit(transport, 1)
    assert base64.b64decode(first["image"]) == webui.library_files["Standing/relaxed.png"]
    assert base64.b64decode(second["image"]) == webui.library_files["Walking/forward.png"]
    assert (first["weight"], first["guidance_end"]) == (1.0, 1.0)
    assert (second["weight"], second["guidance_end"]) == (0.6, 0.8)
    assert "alwayson_scripts" not in posts[2]  # the disabled slot is ordinary unconditioned work


def test_unconditioned_work_is_byte_for_byte_ordinary(webui: Harness, tmp_path: Path) -> None:
    njr = webui.build([_slot(0, "a plain portrait")])[0]
    transport = _transport()

    entry = _run(njr, transport, tmp_path)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    payload = transport.payloads["/sdapi/v1/txt2img"][0]
    assert "alwayson_scripts" not in payload
    assert "controlnet_openpose" not in json.dumps(_variants(entry)[0], default=str)
    assert not any(path.startswith("/controlnet") for _, path, _ in transport.calls)  # no capability probe either


def test_adetailer_and_upscale_stay_intact_and_are_never_conditioned(webui: Harness, tmp_path: Path) -> None:
    from dataclasses import replace

    from tests.helpers.njr_factory import make_stage_config

    njr = webui.build([_slot(0, "a person", controlnet_openpose=POSE_A)])[0]
    chain = (
        njr.stages[0],
        make_stage_config(
            "adetailer", model="sdxl.safetensors", extra={"adetailer_model": "face_yolov8n.pt", "prompt": "detailed face"}
        ),
        make_stage_config(
            "upscale", model="sdxl.safetensors", extra={"upscaler": "R-ESRGAN 4x+", "upscale_factor": 2.0}
        ),
    )
    transport = _transport()

    entry = _run(replace(njr, stages=chain), transport, tmp_path)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    posts = [path for _, path, _ in transport.generation_calls]
    assert posts[0] == "/sdapi/v1/txt2img" and "/sdapi/v1/img2img" in posts and posts[-1] == "/sdapi/v1/extra-single-image"
    assert _unit(transport)["model"] == ADVERTISED  # the base generation is conditioned ...
    face_refinement = transport.payloads["/sdapi/v1/img2img"][0]
    assert set(face_refinement["alwayson_scripts"]) == {"ADetailer"}  # ... the refinement is not, and keeps its script
    assert len(transport.payloads["/sdapi/v1/txt2img"]) == 1


# --- refusals happen before any generation dispatch -----------------------------------------------------------


def _failed_without_dispatch(entry, transport: FakeWebUITransport, *needles: str) -> None:
    assert entry.status is JobStatus.FAILED
    assert transport.generation_calls == []
    text = str(entry.error_message or "")
    for needle in needles:
        assert needle in text, (needle, text)


def test_forge_without_the_controlnet_extension_is_refused_with_no_fallback(webui: Harness, tmp_path: Path) -> None:
    njr = webui.build([_slot(0, "a person", controlnet_openpose=POSE_A)])[0]
    transport = FakeWebUITransport(flavor="forge", checkpoint=SDXL)  # reachable Forge, ControlNet not registered

    entry = _run(njr, transport, tmp_path)

    _failed_without_dispatch(entry, transport, "ControlNet extension")


def test_an_unlisted_controlnet_model_is_refused_actionably(webui: Harness, tmp_path: Path) -> None:
    njr = webui.build([_slot(0, "a person", controlnet_openpose=POSE_A)])[0]
    transport = _transport(models=["a_different_model [11111111]"])

    entry = _run(njr, transport, tmp_path)

    _failed_without_dispatch(entry, transport, "does not list the ControlNet model", "a_different_model")


def test_a_missing_preprocessor_none_is_refused(webui: Harness, tmp_path: Path) -> None:
    njr = webui.build([_slot(0, "a person", controlnet_openpose=POSE_A)])[0]

    entry = _run(njr, _transport(modules=["canny"]), tmp_path)

    assert entry.status is JobStatus.FAILED and "'None' preprocessor" in str(entry.error_message)


def test_a_snapshot_that_changed_after_admission_refuses_dispatch(webui: Harness, tmp_path: Path) -> None:
    njr = webui.build([_slot(0, "a person", controlnet_openpose=POSE_A)])[0]
    Path(FrozenOpenPose.from_config(njr.config["controlnet_openpose"]).snapshot_path).write_bytes(b"swapped")
    transport = _transport()

    entry = _run(njr, transport, tmp_path)

    _failed_without_dispatch(entry, transport, "changed after the job was admitted")


def test_an_a1111_job_with_conditioning_is_refused_not_silently_unconditioned(
    webui: Harness, tmp_path: Path
) -> None:
    from dataclasses import replace

    njr = webui.build([_slot(0, "a person", controlnet_openpose=POSE_A)])[0]
    a1111 = replace(
        njr,
        workload=replace(njr.workload, backend_options={"image": {"backend_id": "a1111_webui"}}),
    )
    transport = FakeWebUITransport(flavor="a1111", checkpoint=SDXL)

    entry = _run(a1111, transport, tmp_path)

    _failed_without_dispatch(entry, transport, "not supported")


# --- replay ------------------------------------------------------------------------------------------------------


def test_replay_gets_a_fresh_identity_and_the_original_verified_input(webui: Harness, tmp_path: Path) -> None:
    original = webui.build([_slot(0, "a person", controlnet_openpose=POSE_A)])[0]
    replay = compile_replay_intent(ReplayIntent(record=original), id_fn=lambda: "replay-1")

    assert replay.job_id == "replay-1" != original.job_id
    assert replay.source.parent_job_id == original.job_id
    assert replay.config["controlnet_openpose"] == original.config["controlnet_openpose"]

    # The library file is replaced after the original was compiled: the replay still conditions on the frozen bytes.
    (webui.library / "Standing" / "relaxed.png").write_bytes(b"replaced in the library")
    transport = _transport()

    entry = _run(replay, transport, tmp_path)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    assert base64.b64decode(_unit(transport)["image"]) == webui.library_files["Standing/relaxed.png"]


def test_replay_fails_explicitly_when_the_original_input_is_unavailable(webui: Harness, tmp_path: Path) -> None:
    original = webui.build([_slot(0, "a person", controlnet_openpose=POSE_A)])[0]
    Path(FrozenOpenPose.from_config(original.config["controlnet_openpose"]).snapshot_path).unlink()
    replay = compile_replay_intent(ReplayIntent(record=original), id_fn=lambda: "replay-2")
    transport = _transport()

    entry = _run(replay, transport, tmp_path)

    _failed_without_dispatch(entry, transport, "no longer available")


def test_replay_input_verification_names_the_conditioning_image(webui: Harness) -> None:
    from src.pipeline.replay_input_verification import frozen_input_checks, verify_inputs

    original = webui.build([_slot(0, "a person", controlnet_openpose=POSE_A)])[0]
    checks = frozen_input_checks(original)

    assert [check.label for check in checks] == ["OpenPose conditioning image"]
    assert verify_inputs(checks) == []
    Path(checks[0].path).write_bytes(b"different bytes")
    issues = verify_inputs(checks)
    assert [issue.label for issue in issues] == ["OpenPose conditioning image"]
    assert "changed since the job was created" in issues[0].describe()


def test_the_detect_map_forge_appends_is_not_recorded_as_a_second_result(webui: Harness, tmp_path: Path) -> None:
    njr = webui.build([_slot(0, "a person", controlnet_openpose=POSE_A)])[0]
    transport = _transport(detect_maps=True)

    entry = _run(njr, transport, tmp_path)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    variants = _variants(entry)
    assert len(variants) == 1  # the job's artifact set is the generated image only
    assert variants[0]["controlnet_openpose"]["control_images_discarded"] == 1
    saved = [p for p in (tmp_path / "run").rglob("*.png") if "batch1" in p.name]
    assert saved == []
