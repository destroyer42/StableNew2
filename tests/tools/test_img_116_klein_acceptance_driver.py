"""PR-IMG-116 acceptance driver: fakes only (no process, GPU or WebUI). The physical smokes are separate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

import src.image_backends.forge_webui_backend as forge_backend_module
import tools.acceptance.img_116_klein_acceptance as driver
from src.api.forge_client import ForgeWebUIClient
from src.image_backends.forge_klein_profile import latest_klein_profile
from src.image_backends.forge_klein_readiness import HostMemorySnapshot
from tests.helpers.fake_webui_transport import FakeWebUITransport
from tests.tools.test_img_forge_100_acceptance_driver import (
    canonical_context,  # noqa: F401  (production admission stays real)
)

KLEIN = "flux-2-klein-4b-fp8.safetensors"
MODULES = [
    {"model_name": "qwen_3_4b.safetensors", "filename": "/d/models/text_encoder/qwen_3_4b.safetensors"},
    {"model_name": "flux2-vae.safetensors", "filename": "/d/models/VAE/flux2-vae.safetensors"},
]


@pytest.fixture(autouse=True)
def _host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        forge_backend_module, "read_host_memory",
        lambda: HostMemorySnapshot(total_bytes=34_107_092_992, available_bytes=17_000_000_000),
    )
    monkeypatch.setattr(forge_backend_module, "verify_klein_assets", lambda profile, **_k: {"stub": True})
    monkeypatch.setattr(driver, "_fault_events", lambda _start: [])
    monkeypatch.setattr(driver, "verify_installed_assets", lambda _dir: {"stubbed": True})


def _args(tmp_path: Path, smoke: str, **extra) -> argparse.Namespace:
    return argparse.Namespace(
        smoke=smoke, reports_dir=tmp_path / f"rep-{smoke}-{extra.pop('tag', '0')}", job_id="",
        approved_intent_sha256=extra.pop("approved_intent_sha256", ""),
        timeout_seconds=60.0, dry=extra.pop("dry", True), forge_data_dir=tmp_path / "data", source_artifact=extra.pop("source", None),
        endpoint="http://127.0.0.1:7871", **extra,
    )


def _client() -> tuple[ForgeWebUIClient, FakeWebUITransport]:
    transport = FakeWebUITransport(flavor="forge", checkpoint=KLEIN, modules=MODULES, seed=424242)
    client = ForgeWebUIClient(base_url="http://127.0.0.1:7871", options_write_enabled=True)
    client._session.request = transport  # type: ignore[method-assign]
    client._options_min_interval_seconds = 0.0
    return client, transport


def _intent(args: argparse.Namespace) -> dict:
    return json.loads((Path(args.reports_dir) / "intent.json").read_text(encoding="utf-8"))


def test_smoke_a_is_compiled_by_the_production_builder_into_the_frozen_klein_intent(tmp_path: Path) -> None:
    args = _args(tmp_path, "A")
    assert driver.run(args, driver.InjectedRuntime()) == driver.EXIT_DRY
    njr = _intent(args)["njr"]
    config = njr["workload"]["config"]
    assert njr["workload"]["backend_options"]["image"] == {"backend_id": "forge_webui", "model_profile": {"id": "flux2_klein_4b_fp8", "version": 2}}
    assert (config["steps"], config["cfg_scale"], config["sampler_name"], config["scheduler"]) == (4, 1.0, "Euler", "Beta")
    assert (config["width"], config["height"], config["seed"]) == (768, 1024, 424242)
    assert njr["workload"]["negative_prompt"] == ""
    assert [s["stage_type"] for s in njr["stages"]] == ["txt2img"]


def test_smoke_b_is_built_by_the_production_review_handler_as_one_img2img_job(tmp_path: Path) -> None:
    source = tmp_path / "a.png"
    Image.new("RGB", (768, 1024), (80, 110, 70)).save(source)
    args = _args(tmp_path, "B", source=source)
    assert driver.run(args, driver.InjectedRuntime()) == driver.EXIT_DRY
    njr = _intent(args)["njr"]
    assert [s["stage_type"] for s in njr["stages"]] == ["img2img"]
    assert njr["workload"]["input_image_paths"] == [str(source.resolve())]
    assert njr["workload"]["backend_options"]["image"]["model_profile"]["id"] == "flux2_klein_4b_fp8"
    assert njr["workload"]["positive_prompt"] == driver.EDIT_INSTRUCTION
    assert njr["workload"]["negative_prompt"] == ""


def test_physical_execution_needs_the_approved_digest(tmp_path: Path) -> None:
    args = _args(tmp_path, "A", dry=False)
    with pytest.raises(PermissionError, match="approved intent digest"):
        driver.run(args, driver.InjectedRuntime())


@pytest.mark.usefixtures("canonical_context")
def test_smoke_a_then_b_complete_end_to_end_with_fakes_one_dispatch_each(tmp_path: Path) -> None:
    client, transport = _client()
    dry = _args(tmp_path, "A", tag="dry")
    driver.run(dry, driver.InjectedRuntime())
    digest = _intent(dry)["intent_sha256"]
    args = _args(tmp_path, "A", dry=False, approved_intent_sha256=digest)
    assert driver.run(args, driver.InjectedRuntime(), client=client) == driver.EXIT_COMPLETED
    report = json.loads((Path(args.reports_dir) / "acceptance.json").read_text(encoding="utf-8"))
    assert report["job"]["status"] == "completed"
    assert report["job"]["klein_evidence"]["model_profile"]["version"] == 2
    assert report["job"]["image_backend_id"] == "forge_webui"
    assert [p for _, p, _ in transport.generation_calls] == ["/sdapi/v1/txt2img"]
    assert report["pre_run_memory"]["available_gb"] > 0 and report["pre_run_memory"]["total_gb"] > 0
    assert report["pre_dispatch_memory"]["available_gb"] > 0  # immediately before generation dispatch
    assert "forge_tree_private_peak_mib" in report["job"]["forge_tree_memory"]

    # Smoke B on a qualified-geometry source (the 1x1 fake output cannot stand in for it)
    source = tmp_path / "a768.png"
    Image.new("RGB", (768, 1024), (80, 110, 70)).save(source)
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    dry_b = _args(tmp_path, "B", tag="dry", source=source)
    driver.run(dry_b, driver.InjectedRuntime())
    approved = _intent(dry_b)["intent_sha256"]
    client_b, transport_b = _client()
    args_b = _args(tmp_path, "B", dry=False, approved_intent_sha256=approved, source=source)
    assert driver.run(args_b, driver.InjectedRuntime(), client=client_b) == driver.EXIT_COMPLETED
    rep_b = json.loads((Path(args_b.reports_dir) / "acceptance.json").read_text(encoding="utf-8"))
    assert [p for _, p, _ in transport_b.generation_calls] == ["/sdapi/v1/img2img"]
    assert "alwayson_scripts" not in transport_b.payloads["/sdapi/v1/img2img"][0]
    assert rep_b["source_sha256_before"] == rep_b["source_sha256_after"] == sha
    assert rep_b["job"]["klein_evidence"]["source_image"]["sha256"] == sha


def test_the_review_guard_refuses_an_njr_that_differs_from_the_approved_intent(tmp_path: Path) -> None:
    source = tmp_path / "a.png"
    Image.new("RGB", (768, 1024)).save(source)
    from types import SimpleNamespace

    real = SimpleNamespace(submit_njrs=lambda njrs, policy: [n.job_id for n in njrs])
    with driver.forge_selected_in_memory():
        guarded = driver._CapturingService(real=real, approved_digest="0" * 64)
        with pytest.raises(PermissionError, match="does not match the approved intent digest"):
            driver.run_review_handler(source, guarded, tmp_path / "out")


def test_installed_asset_verification_rejects_a_wrong_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()  # use the real verifier here
    profile = latest_klein_profile()
    for asset in profile.assets:
        target = tmp_path / "models" / asset.models_subdir / asset.filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
    with pytest.raises(ValueError, match="wrong size"):
        driver.verify_installed_assets(tmp_path)


def test_driver_never_writes_production_settings_and_submits_each_job_once() -> None:
    text = Path(driver.__file__).read_text(encoding="utf-8")
    assert "save_settings" not in text and "write_text(" not in text
    assert text.count("stack.service.submit_njrs(") == 1  # Smoke A; Smoke B submits via the Review handler once
