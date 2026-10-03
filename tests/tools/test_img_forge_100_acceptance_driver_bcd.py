# ruff: noqa: F811  (the canonical_context fixture is imported from the Pair-A driver tests)
"""PR-IMG-FORGE-100: the acceptance driver's frozen Pair B/C/D cases, proven with mocked HTTP only.

Same canonical stack as the Pair-A proofs (JobService -> SQLite -> run_njr -> backend registry -> executor),
a fake transport, no WebUI/GPU/model. They prove that each frozen case reaches the dispatched request exactly,
that mutable globals cannot reach it, and that assets are verified before any runtime starts.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest

from tests.helpers.fake_webui_transport import TINY_PNG_B64
from tests.tools.test_img_forge_100_acceptance_driver import (  # noqa: F401 - fixture + helpers
    BACKENDS,
    INTENT,
    REPO_ROOT,
    SETTINGS,
    _client,
    _evidence,
    canonical_context,
)
from tools.acceptance import img_forge_100_acceptance as driver

SOURCE_BYTES = base64.b64decode(TINY_PNG_B64)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def matrix_file(tmp_path: Path):
    """An authoritative-matrix stand-in: the tracked settings/cases plus assets that exist on disk."""

    assets = {}
    for name in ("checkpoint", "lora", "input", "face_detector", "hand_detector", "upscaler"):
        path = tmp_path / "assets" / f"{name}.bin"
        path.parent.mkdir(exist_ok=True)
        data = SOURCE_BYTES if name == "input" else name.encode()
        path.write_bytes(data)
        assets[name] = {"path": str(path), "sha256": _sha(data)}
    matrix = {"package": "PR-IMG-FORGE-100", "settings": copy.deepcopy(SETTINGS), "cases": copy.deepcopy(INTENT["cases"]), "assets": assets}
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(matrix), encoding="utf-8")
    return path, matrix


def _args(letter: str, backend: str, reports: Path, matrix_path: Path, matrix: dict) -> argparse.Namespace:
    case = next(c for c in matrix["cases"] if c["case_id"] == f"{letter}-{backend}")
    njr = driver.freeze_case_njr(matrix, case, job_id="digest-only", output_dir=reports)
    return argparse.Namespace(
        backend=backend, case=letter, matrix=matrix_path, reports_dir=reports, intent=driver.DEFAULT_INTENT,
        approved_intent_sha256=driver.intent_digest(njr), job_id=f"test-forge100-{letter}-{backend}",
        timeout_seconds=60.0, dry=False, endpoint="http://127.0.0.1:1",
    )


class _SpyRuntime(driver.InjectedRuntime):
    started = False

    def start(self):
        self.started = True
        return super().start()


def _drive(letter: str, backend: str, tmp_path: Path, matrix_file, runtime=None):
    path, matrix = matrix_file
    reports = tmp_path / "evidence"
    client, transport = _client(backend)
    try:
        code = driver.run(_args(letter, backend, reports, path, matrix), runtime or driver.InjectedRuntime(), client=client)
    finally:
        client.close()
    return code, transport, reports


@pytest.mark.parametrize("backend", BACKENDS)
def test_pair_b_dispatches_the_exact_frozen_prompt_with_the_lora_token_once(backend, canonical_context, tmp_path, matrix_file):
    code, transport, reports = _drive("B", backend, tmp_path, matrix_file)

    assert code == driver.EXIT_COMPLETED, _evidence(reports)
    assert [p for _, p, _ in transport.generation_calls] == ["/sdapi/v1/txt2img"]  # one dispatch
    [payload] = transport.payloads["/sdapi/v1/txt2img"]
    expected = SETTINGS["prompt"] + f" <lora:{SETTINGS['lora_name']}:{SETTINGS['lora_strength']}>"
    assert payload["prompt"] == expected and payload["prompt"].count("<lora:") == 1
    assert "<lora:add-detail-xl:0.82>" in payload["prompt"]
    assert payload["negative_prompt"] == SETTINGS["negative_prompt"] and "<lora:" not in payload["negative_prompt"]
    assert payload["seed"] == 424242 and payload["sd_model"] == SETTINGS["checkpoint"] and payload["sd_vae"] == "Automatic"
    assert "MUTABLE" not in json.dumps(payload)  # hostile mutable globals cannot reach frozen intent
    assert _evidence(reports)["assets_verified"].keys() == {"checkpoint", "lora"}


@pytest.mark.parametrize("backend", BACKENDS)
def test_pair_c_dispatches_the_frozen_source_denoise_seed_and_geometry_and_never_mutates_the_source(
    backend, canonical_context, tmp_path, matrix_file
):
    code, transport, reports = _drive("C", backend, tmp_path, matrix_file)

    assert code == driver.EXIT_COMPLETED, _evidence(reports)
    assert [p for _, p, _ in transport.generation_calls] == ["/sdapi/v1/img2img"]
    [payload] = transport.payloads["/sdapi/v1/img2img"]
    import io

    from PIL import Image

    def decoded(data: bytes):
        image = Image.open(io.BytesIO(data)).convert("RGBA")
        return image.size, image.tobytes()

    # StableNew re-encodes the source to PNG before dispatch; the decoded pixels are the frozen source's.
    assert [decoded(base64.b64decode(image.split(",")[-1])) for image in payload["init_images"]] == [decoded(SOURCE_BYTES)]
    assert payload["denoising_strength"] == 0.3 and payload["seed"] == 424242
    assert (payload["width"], payload["height"]) == (480, 832)  # the frozen geometry, not the txt2img one
    assert payload["prompt"] == SETTINGS["prompt"] and payload["negative_prompt"] == SETTINGS["negative_prompt"]
    assert "<lora:" not in payload["prompt"] and "MUTABLE" not in json.dumps(payload)
    evidence = _evidence(reports)
    assert evidence["input_sha256_after"] == evidence["assets_verified"]["input"]["sha256"] == _sha(SOURCE_BYTES)


@pytest.mark.parametrize("backend", BACKENDS)
def test_pair_d_runs_txt2img_then_face_and_hand_adetailer_then_the_frozen_upscale(
    backend, canonical_context, tmp_path, matrix_file
):
    code, transport, reports = _drive("D", backend, tmp_path, matrix_file)

    assert code == driver.EXIT_COMPLETED, _evidence(reports)
    assert [p for _, p, _ in transport.generation_calls] == [
        "/sdapi/v1/txt2img", "/sdapi/v1/img2img", "/sdapi/v1/extra-single-image",
    ]
    [base] = transport.payloads["/sdapi/v1/txt2img"]
    assert base["seed"] == 424242 and base["prompt"] == SETTINGS["prompt"] and "<lora:" not in base["prompt"]
    [outer] = transport.payloads["/sdapi/v1/img2img"]
    assert outer["seed"] == 424242  # the repaired contract: the outer ADetailer request never falls back to -1
    units = [a for a in outer["alwayson_scripts"]["ADetailer"]["args"] if isinstance(a, dict)]
    assert [u["ad_model"] for u in units] == ["face_yolov8n.pt", "hand_yolov8n.pt"]
    frozen = SETTINGS["adetailer"]
    assert (units[0]["ad_confidence"], units[0]["ad_denoising_strength"], units[0]["ad_steps"]) == (
        frozen["adetailer_confidence"], frozen["adetailer_denoise"], frozen["adetailer_steps"])
    assert (units[1]["ad_confidence"], units[1]["ad_denoising_strength"], units[1]["ad_steps"]) == (
        frozen["adetailer_hands_confidence"], frozen["adetailer_hands_denoise"], frozen["adetailer_hands_steps"])
    [upscale] = transport.payloads["/sdapi/v1/extra-single-image"]
    assert upscale["upscaling_resize"] == 1.5 and upscale["upscaler_1"] == SETTINGS["upscale"]["upscaler"]
    assert "MUTABLE" not in json.dumps([base, outer, upscale])
    assert _evidence(reports)["assets_verified"].keys() == {"checkpoint", "face_detector", "hand_detector", "upscaler"}


def test_a_changed_asset_stops_before_any_runtime_starts_or_job_is_submitted(canonical_context, tmp_path, matrix_file):
    path, matrix = matrix_file
    Path(matrix["assets"]["lora"]["path"]).write_bytes(b"tampered")
    runtime = _SpyRuntime()

    code, transport, reports = _drive("B", "forge_webui", tmp_path, matrix_file, runtime=runtime)

    assert code == driver.EXIT_NOT_SUBMITTED and not runtime.started
    assert "Asset changed: lora" in _evidence(reports)["error"]
    assert not transport.calls  # nothing was sent anywhere


def test_the_matrix_must_agree_with_the_tracked_intent_and_is_required_for_b_c_d(canonical_context, tmp_path, matrix_file):
    path, matrix = matrix_file
    changed = copy.deepcopy(matrix)
    changed["settings"]["adetailer"]["adetailer_confidence"] = 0.5
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="differ from the tracked frozen intent"):
        driver.load_frozen_case(path, "D", "forge_webui", driver.DEFAULT_INTENT)

    path.write_text(json.dumps(matrix), encoding="utf-8")
    with pytest.raises(ValueError, match="no case"):
        driver.load_frozen_case(path, "Z", "forge_webui", driver.DEFAULT_INTENT)
    args = _args("B", "forge_webui", tmp_path / "e", path, matrix)
    args.matrix = None
    with pytest.raises(ValueError, match="--matrix"):
        driver.run(args, driver.InjectedRuntime())


@pytest.mark.parametrize("letter", ["B", "C", "D"])
def test_matched_arms_differ_only_in_backend_identity_and_job_location(letter, tmp_path, matrix_file):
    path, matrix = matrix_file
    njrs = {}
    for backend in BACKENDS:
        case = next(c for c in matrix["cases"] if c["case_id"] == f"{letter}-{backend}")
        njrs[backend] = driver.freeze_case_njr(matrix, case, job_id="same", output_dir=tmp_path / backend)

    a, f = (json.loads(json.dumps(njrs[b].to_dict(), default=str)) for b in BACKENDS)
    for data, backend in ((a, "a1111_webui"), (f, "forge_webui")):
        assert data["workload"]["backend_options"]["image"]["backend_id"] == backend
        data["workload"]["backend_options"] = None
        data["workload"]["config"].pop("backend_options", None)  # the img2img builder echoes it into config
        data["workload"]["metadata"] = None
        data["output_plan"] = None
    assert a == f  # prompts, seeds, stages, geometry: semantically identical intent on both backends
