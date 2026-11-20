"""PR-IMG-FLUX-130: generic FLUX families through the one canonical image path.

``NJR -> JobService -> SQLite -> PipelineRunner.run_njr -> ForgeWebUIImageBackend -> executor -> ForgeWebUIClient`` with a
stateful Forge-shaped fake (no GPU, no network, no model bytes). The FLUX.1 [dev] family profile dispatches exactly its
frozen settings with the pinned modules; a FLUX.1 [dev] transformer without the profile, and FLUX.2 Klein 9B in any
container, are refused before any module write or generation POST. The module and memory byte checks are stubbed here;
they have their own unit tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.image_backends.forge_flux1_profile import FLUX1_DEV_PROFILE_V1 as P
from src.image_backends.forge_flux1_profile import FLUX1_UNPROFILED_HINT, flux_variant_refusal
from src.image_backends.forge_klein_readiness import HostMemorySnapshot
from src.queue.job_model import JobStatus
from tests.assets.flux_fixtures_130 import (
    FTYPE_Q6_K,
    GGML_Q6_K,
    flux1_table,
    klein_table,
    write_gguf,
)
from tests.helpers.fake_webui_transport import FakeWebUITransport
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config
from tests.helpers.njr_queue_harness import run_njr_via_queue
from tests.integration.test_pr_img_116_klein_canonical_path import _client

FLUX1 = "flux1-dev-Q4_K_S.gguf"
NINE_B_GGUF = "flux-2-klein-base-9b-Q6_K.gguf"
SDXL = "sdxl.safetensors"


@pytest.fixture(autouse=True)
def _no_physical_assets(monkeypatch):
    monkeypatch.setattr("src.pipeline.executor.collect_gpu_snapshot", lambda: None)
    monkeypatch.setattr(
        "src.image_backends.forge_webui_backend.read_host_memory", lambda: HostMemorySnapshot(34_000_000_000, 1, 0)
    )
    monkeypatch.setattr("src.image_backends.forge_webui_backend.verify_flux1_assets", lambda profile, **kw: {
        "forge": {"revision": P.forge_revision},
        "transformer": {"name": kw["model_name"], "variant": "flux1_dev", "verified": "structure"},
        **{a.role: {"name": a.filename, "sha256": a.sha256, "verified": "sha256"} for a in P.modules},
    })


@pytest.fixture
def files(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "models" / "Stable-diffusion"
    return {
        FLUX1: write_gguf(root / FLUX1, flux1_table()),
        NINE_B_GGUF: write_gguf(root / NINE_B_GGUF, klein_table("9b"), tensor_type=GGML_Q6_K, file_type=FTYPE_Q6_K),
    }


def _transport(files: dict[str, Path], checkpoint: str = SDXL) -> FakeWebUITransport:
    return FakeWebUITransport(
        flavor="forge", checkpoint=checkpoint, seed=4242,
        modules=[{"model_name": a.filename, "filename": "/data/" + a.filename} for a in P.modules],
        checkpoint_files={name: str(path) for name, path in files.items()},
    )


def _njr(model: str = FLUX1, *, profile: bool = True, negative: str = "", stages=("txt2img",), **config):
    data = {
        "model": model, "sampler_name": "Euler", "scheduler": "Simple", "steps": 20, "cfg_scale": 1.0,
        "width": 1024, "height": 1024, "clip_skip": 1, "vae": "", "distilled_cfg_scale": 3.5,
        "prompt_optimizer": {"enabled": False},
        "pipeline": {"apply_global_negative_txt2img": False, "apply_global_positive_txt2img": False},
        "global_positive_prompt": "", "global_negative_prompt": "", "global_prompt_policy_source": "frozen_njr",
        **config,
    }
    image = {"backend_id": "forge_webui"}
    if profile:
        image["model_profile"] = P.reference()
    chain = {
        "txt2img": make_stage_config("txt2img", model=model, steps=data["steps"], cfg_scale=data["cfg_scale"],
                                     sampler_name="Euler", scheduler="Simple"),
        "adetailer": make_stage_config("adetailer", model=model, extra={"adetailer_model": "face_yolov8n.pt"}),
    }
    return make_pipeline_njr(
        positive_prompt="A lighthouse on a cliff at dusk, oil painting.", negative_prompt=negative, base_model=model,
        sampler_name="Euler", steps=data["steps"], cfg_scale=data["cfg_scale"], width=data["width"],
        height=data["height"], seed=4242, stage_chain=tuple(chain[name] for name in stages), config=data,
        backend_options={"image": image},
    )


def _posts(transport: FakeWebUITransport) -> list[tuple[str, str]]:
    return [(verb, path) for verb, path, _ in transport.calls if verb == "POST"]


def test_the_family_profile_dispatches_its_frozen_settings_with_the_pinned_modules(files, tmp_path):
    transport = _transport(files)
    entry = run_njr_via_queue(_njr(), _client(transport), artifact_root=tmp_path / "out")
    assert entry.status is JobStatus.COMPLETED, entry.error_message
    assert len(transport.generation_calls) == 1
    payload = transport.generation_calls[0][2]
    assert (payload["steps"], payload["sampler_name"], payload["scheduler"]) == (20, "Euler", "Simple")
    assert payload["cfg_scale"] == 1.0 and payload["distilled_cfg_scale"] == 3.5
    assert payload["negative_prompt"] == "" and (payload["width"], payload["height"]) == (1024, 1024)
    assert payload["batch_size"] == payload["n_iter"] == 1
    assert transport.generation_module_state == [sorted(a.filename for a in P.modules)]
    assert payload["sd_model"] == FLUX1 and payload["clip_skip"] == 1  # the selected, structurally verified file
    assert entry.snapshot["normalized_job"]["workload"]["backend_options"]["image"]["model_profile"] == P.reference()
    evidence = entry.result["variants"][0]["image_backend_metadata"]["flux1_profile"]
    assert evidence["model_profile"] == P.reference() and evidence["family"] == "flux1"
    assert evidence["transformer"]["name"] == FLUX1
    assert evidence["asset_identity"]["transformer"]["verified"] == "structure"
    assert evidence["qualification_status"] == "not physically qualified"


@pytest.mark.parametrize(
    "change",
    [
        {"negative": "blurry"},
        {"steps": 28},
        {"cfg_scale": 3.5},
        {"width": 1280, "height": 720},
        {"distilled_cfg_scale": 5.0},
        {"stages": ("txt2img", "adetailer")},
        {"vae": "sdxl_vae.safetensors"},
    ],
)
def test_work_outside_the_envelope_fails_before_any_generation(files, change):
    transport = _transport(files)
    entry = run_njr_via_queue(_njr(**change), _client(transport))
    assert entry.status is JobStatus.FAILED
    assert transport.generation_calls == []


def test_a_flux1_dev_transformer_without_the_profile_is_refused_before_any_write(files):
    transport = _transport(files)
    before = dict(transport.options)
    entry = run_njr_via_queue(_njr(profile=False), _client(transport))
    assert entry.status is JobStatus.FAILED
    assert FLUX1_UNPROFILED_HINT in str(entry.error_message)
    assert _posts(transport) == [] and transport.generation_calls == []
    assert transport.options == before


def test_a_gguf_klein_9b_is_refused_before_any_write_or_generation(files):
    transport = _transport(files)
    entry = run_njr_via_queue(
        _njr(NINE_B_GGUF, profile=False, sampler_name="Euler", scheduler="Beta", steps=20, cfg_scale=4.0),
        _client(transport),
    )
    assert entry.status is JobStatus.FAILED
    message = str(entry.error_message)
    assert "FLUX.2 Klein 9B-class, GGUF Q6_K" in message and flux_variant_refusal("flux2_klein_9b") in message
    assert _posts(transport) == [] and transport.generation_calls == []


def test_a_frozen_flux1_reference_on_a_9b_checkpoint_is_refused_at_dispatch(files, monkeypatch):
    """The frozen profile never admits a file by name: the served structure decides (real verifier, stubbed runtime)."""

    from types import SimpleNamespace

    from src.image_backends import forge_klein_assets, forge_webui_backend

    monkeypatch.setattr(forge_webui_backend, "verify_flux1_assets", forge_klein_assets.verify_flux1_assets)
    manager = SimpleNamespace(
        runtime_identity="forge_webui", owns_process=True, endpoint="http://127.0.0.1:7861",
        launch_session_command=["python", "launch.py", "--data-dir", str(files[FLUX1].parents[2])],
        _config=SimpleNamespace(working_dir="src"),
    )
    monkeypatch.setattr(forge_klein_assets, "_active_manager", lambda: manager)
    monkeypatch.setattr("src.utils.managed_forge_runtime.verify_pinned_launch", lambda *a: {"revision": a[2]})
    transport = _transport(files)
    entry = run_njr_via_queue(_njr(NINE_B_GGUF), _client(transport))
    assert entry.status is JobStatus.FAILED
    assert "Klein 9B-class" in str(entry.error_message)
    assert transport.generation_calls == []
