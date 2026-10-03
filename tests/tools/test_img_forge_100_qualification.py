"""Qualification safety and canonical admission with temporary files and no physical runtime."""

from __future__ import annotations

import copy
import importlib
import json
import subprocess
from pathlib import Path

import pytest

from tools.qualification.img_forge_100 import compare, contact_sheet, preflight, provenance, run


@pytest.fixture
def matrix(tmp_path: Path) -> dict:
    assets = {}
    for name in ("checkpoint", "lora", "input", "face_detector", "hand_detector"):
        path = tmp_path / name
        path.write_bytes(name.encode())
        assets[name] = {"path": str(path), "sha256": provenance.hash_file(path)}
    return {
        "package": "PR-IMG-FORGE-100", "stable_sha": "a" * 40, "assets": assets,
        "endpoints": {"a1111_webui": "http://127.0.0.1:7860", "forge_webui": "http://127.0.0.1:7871"},
        "observed_comfy_endpoint": "http://127.0.0.1:8189",
        "settings": {"checkpoint": "sdxl.safetensors", "vae": "Automatic", "seed": 424242,
                     "steps": 24, "cfg_scale": 5.5, "sampler_name": "Euler a", "scheduler": "Karras",
                     "width": 832, "height": 1216, "prompt": "a lighthouse at dusk",
                     "negative_prompt": "lowres, blurry", "lora_name": "add-detail-xl",
                     "lora_strength": 0.82, "img2img_denoise": 0.3,
                     "adetailer": {"enable_face_pass": True, "enable_hands_pass": True,
                                   "adetailer_model": "face_yolov8n.pt",
                                   "adetailer_hands_model": "hand_yolov8n.pt"},
                     "upscale": {"upscaler": "R-ESRGAN 4x+", "upscaling_resize": 1.5}},
        "cases": [{"case_id": case_id, "scenario": scenario, "backend": backend,
                   "stages": list(run.CHAINS[scenario])}
                  for scenario in run.CHAINS for backend in run.BACKENDS
                  for case_id in [f"{scenario}-{backend}"]],
    }


def _frozen(matrix: dict) -> tuple[dict, dict]:
    descriptor = provenance.load_descriptor(Path(__file__).resolve().parents[2] / "config" / "forge_qualification_runtime.json")
    evidence = {"matrix_sha256": provenance.digest(matrix), "stable_sha": matrix["stable_sha"],
                "forge": {"commit": descriptor["source"]["commit"]},
                "adetailer": {"commit": descriptor["adetailer"]["commit"]}}
    evidence["provenance_sha256"] = provenance.digest(evidence)
    flights = {b: {"ready": True, "endpoint": matrix["endpoints"][b]} for b in run.BACKENDS}
    return evidence, flights


def test_imports_have_no_network_process_or_file_work(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("Import performed external work")
    monkeypatch.setattr(subprocess, "check_output", forbidden)
    monkeypatch.setattr(preflight, "urlopen", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    for name in ("provenance", "preflight", "runtime_capture", "run", "compare", "contact_sheet"):
        importlib.reload(importlib.import_module(f"tools.qualification.img_forge_100.{name}"))


def test_exclusive_evidence_and_changed_asset_fail_closed(matrix, tmp_path) -> None:
    path = tmp_path / "provenance.json"
    provenance.write_exclusive(path, {"frozen": True})
    with pytest.raises(FileExistsError):
        provenance.write_exclusive(path, {"frozen": False})
    Path(matrix["assets"]["lora"]["path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="Asset changed"):
        preflight.local_preflight(matrix)


@pytest.mark.parametrize("endpoint", ["http://127.0.0.1:7860", "http://other:7871", "http://127.0.0.1",
                                     "http://127.0.0.1:7871/path", "http://127.0.0.1:7871?x=1"])
def test_forge_endpoint_requires_exact_explicit_loopback_port(endpoint) -> None:
    with pytest.raises(ValueError):
        preflight.explicit_endpoint(endpoint, "forge_webui")


def _api(flavor="forge") -> dict:
    routes = {p: {v: {}} for p, v in preflight.REQUIRED_ROUTES.items()}
    return {
        "/openapi.json": {"paths": routes},
        "/sdapi/v1/cmd-flags": {"forge_ref_a1111_home": "/existing", "ad_no_huggingface": True}
        if flavor == "forge" else {},
        "/sdapi/v1/sd-modules": [{"model_name": "sdxl_vae.safetensors"}] if flavor == "forge" else None,
        "/sdapi/v1/sd-vae": [] if flavor == "a1111" else None,
        "/sdapi/v1/sd-models": [{"model_name": "sdxl", "filename": "/models/sdxl.safetensors"}],
        "/sdapi/v1/options": {}, "/sdapi/v1/scripts": {"txt2img": ["ADetailer", "ControlNet"], "img2img": []},
        "/sdapi/v1/script-info": [], "/sdapi/v1/loras": [{"name": "add-detail-xl"}],
        "/sdapi/v1/upscalers": [{"name": "R-ESRGAN 4x+"}],
        "/adetailer/v1/ad_model": {"ad_model": ["face_yolov8n.pt", "hand_yolov8n.pt"]},
    }


def test_preflight_is_read_only_explicit_and_rejects_identity_mismatch() -> None:
    calls = []
    selected = {"checkpoint": "sdxl.safetensors", "vae": "Automatic", "lora": "add-detail-xl",
                "upscaler": "R-ESRGAN 4x+"}
    def fetch(endpoint, path):
        calls.append((endpoint, path))
        return _api()[path]
    result = preflight.inspect_endpoint("http://127.0.0.1:7871", "forge_webui", selected=selected, fetch=fetch)
    assert result["ready"] and result["controlnet"] == "FORGE_CONTROLNET_RUNTIME_CAPABILITY_PRESENT"
    assert {endpoint for endpoint, _ in calls} == {"http://127.0.0.1:7871"}
    assert {path for _, path in calls} == set(preflight.READ_PATHS)
    assert not any(path in preflight.REQUIRED_ROUTES and preflight.REQUIRED_ROUTES[path] == "post"
                   for _, path in calls if path != "/sdapi/v1/options")
    result = preflight.inspect_endpoint("http://127.0.0.1:7871", "forge_webui", selected=selected,
                                       fetch=lambda endpoint, path: _api("a1111").get(path))
    assert not result["ready"] and not result["checks"]["runtime_identity"]


@pytest.mark.parametrize("change", ["extra_case", "duplicate", "controlnet", "random_seed", "same_endpoint"])
def test_frozen_matrix_rejects_unbounded_or_changed_cases(matrix, change) -> None:
    if change == "extra_case":
        matrix["cases"].append(copy.deepcopy(matrix["cases"][0]))
    elif change == "duplicate":
        matrix["cases"][1] = matrix["cases"][0]
    elif change == "controlnet":
        matrix["cases"][0]["stages"] = ["controlnet"]
    elif change == "random_seed":
        matrix["settings"]["seed"] = -1
    else:
        matrix["endpoints"]["a1111_webui"] = matrix["endpoints"]["forge_webui"]
    with pytest.raises(ValueError):
        run.validate_matrix(matrix)


def test_all_eight_cases_compile_to_immutable_njrs_and_input_only_on_c(matrix, tmp_path) -> None:
    run.validate_matrix(matrix)
    for case in matrix["cases"]:
        njr = run.compile_case(matrix, case, tmp_path)
        assert njr.backend_options["image"]["backend_id"] == case["backend"]
        assert njr.seed == 424242 and njr.images_per_prompt == 1
        assert tuple(s.stage_type for s in njr.stage_chain) == tuple(case["stages"])
        assert bool(njr.input_image_paths) == (case["scenario"] == "C")
        assert ("<lora:add-detail-xl:0.82>" in njr.positive_prompt) == (case["scenario"] == "B")
        if case["scenario"] == "C":
            extra = njr.stage_chain[0].extra
            assert extra["seed"] == 424242 and extra["negative_prompt"] == "lowres, blurry"
            assert (extra["width"], extra["height"]) == (832, 1216)
        projected_config = njr.config
        projected_config["batch_size"] = 2
        assert njr.config["batch_size"] == 1  # The convenience projection cannot mutate the NJR.


def test_unapproved_execution_does_not_create_any_run_or_service(matrix, tmp_path) -> None:
    evidence, flights = _frozen(matrix)
    root = tmp_path / "unapproved"
    with pytest.raises(PermissionError):
        run.execute_matrix(matrix, root, approved_digest=None, provenance=evidence, preflights=flights,
                           service_factory=lambda *args: pytest.fail("Constructed physical services"))
    assert not root.exists()


def test_proposal_blockers_prevent_execution_even_with_matching_digest(matrix, tmp_path) -> None:
    matrix["execution_blockers"] = ["Unclosed install plan"]
    evidence, flights = _frozen(matrix)
    root = tmp_path / "blocked"
    with pytest.raises(ValueError, match="execution blockers"):
        run.execute_matrix(matrix, root, approved_digest=provenance.digest(matrix),
                           provenance=evidence, preflights=flights,
                           service_factory=lambda *args: pytest.fail("Constructed physical services"))
    assert not root.exists()


def test_queue_failure_aborts_without_retry_and_preserves_evidence(matrix, tmp_path) -> None:
    from src.controller.job_service import JobService
    from src.queue.job_queue import JobQueue
    from src.queue.job_repository import JobRepository
    from src.queue.single_node_runner import SingleNodeJobRunner

    dispatched = []
    def factory(data, root):
        repository = JobRepository(root / "jobs.sqlite3")
        queue = JobQueue(repository=repository)
        def fail(job):
            dispatched.append(job.job_id)
            return {"error": "CUDA device lost"}
        worker = SingleNodeJobRunner(queue, fail, poll_interval=0.01)
        return JobService(queue, runner=worker, history_store=repository), repository
    evidence, flights = _frozen(matrix)
    root = tmp_path / "run"
    results = run.execute_matrix(matrix, root, approved_digest=provenance.digest(matrix),
                                 provenance=evidence, preflights=flights, service_factory=factory)
    assert len(dispatched) == len(results) == 1
    assert results[0]["status"] == "failed"
    assert results[0]["snapshot"]["normalized_job"]["workload"]["backend_options"]["image"]["backend_id"] == "a1111_webui"
    assert (root / "jobs.sqlite3").exists() and len(list(root.glob("*.njr.json"))) == 8
    with pytest.raises(FileExistsError):
        run.execute_matrix(matrix, root, approved_digest=provenance.digest(matrix),
                           provenance=evidence, preflights=flights, service_factory=factory)


def test_comparison_missing_seed_never_becomes_pass() -> None:
    assert not compare.compare_settings({"seed": 42}, {})["agreement"]
    assert not compare.compare_settings({"seed": 42}, {"seed": 43})["agreement"]
    arm = {"requested": {"seed": 42}, "reported": {"seed": 42}}
    pair = compare.compare_pair(arm, arm)
    assert pair["perceptual_threshold"] is None
    assert not pair["checks"]["forge"]["artifact_manifest_history"]


def test_contact_sheet_preserves_sources_and_rejects_overwrite(tmp_path) -> None:
    from PIL import Image

    a, f = tmp_path / "a.png", tmp_path / "f.png"
    Image.new("RGB", (60, 80), "red").save(a)
    Image.new("RGB", (80, 60), "blue").save(f)
    hashes = [provenance.hash_file(a), provenance.hash_file(f)]
    output = tmp_path / "sheet.png"
    contact_sheet.create_contact_sheet([("A", a, f)], output, tile=100)
    assert Image.open(output).size == (200, 140)
    assert hashes == [provenance.hash_file(a), provenance.hash_file(f)]
    with pytest.raises(FileExistsError):
        contact_sheet.create_contact_sheet([("A", a, f)], output)


def test_runtime_capture_never_imports_torch_or_mutates_processes(monkeypatch, tmp_path) -> None:
    from tools.qualification.img_forge_100 import runtime_capture

    commands = []
    def command(args, **kwargs):
        commands.append(args)
        return json.dumps({"python": "3.13.16", "packages": {}}) if args[0] == "python" else "RTX 4070 Ti"
    monkeypatch.setattr(runtime_capture, "git_read", lambda *args: "a" * 40)
    result = runtime_capture.capture_runtime(python=Path("python"), forge_root=tmp_path,
                                            adetailer_root=tmp_path, launch_command=["--api"],
                                            process_evidence={"ownership": "external"}, run_command=command)
    assert result["process_evidence"]["ownership"] == "external"
    assert "import torch" not in commands[0][-1]
