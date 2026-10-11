"""IMG155: real NJR/JobService/SQLite/runner/Forge/executor/HTTP path with fake transport."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from src.image_backends.forge_klein_readiness import HostMemorySnapshot
from src.image_backends.forge_zimage_profile import SAMPLING_OPTIONS
from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1 as P
from src.queue.job_model import JobStatus
from tests.helpers.fake_webui_transport import FakeWebUITransport
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config
from tests.helpers.njr_queue_harness import run_njr_via_queue
from tests.integration.test_pr_img_116_klein_canonical_path import _client


@pytest.fixture(autouse=True)
def _no_physical_assets(monkeypatch):
    monkeypatch.setattr("src.image_backends.forge_webui_backend.read_host_memory", lambda: HostMemorySnapshot(34_000_000_000, 1, 0))
    monkeypatch.setattr("src.image_backends.forge_webui_backend.verify_zimage_assets", lambda profile, **kw: {
        "forge": {"revision": P.forge_revision},
        **{a.role: {"name": a.filename, "sha256": a.sha256, "verified": "sha256"} for a in P.assets},
    })


def njr(**changes):
    data = {
        "model": P.transformer.filename, "sampler_name": "Euler", "scheduler": "Beta", "steps": 9,
        "cfg_scale": 1.0, "width": 1024, "height": 1024, "clip_skip": 1,
        "prompt_optimizer": {"enabled": False}, "distilled_cfg_scale": 9,
        "pipeline": {"apply_global_negative_txt2img": False, "apply_global_positive_txt2img": False},
        "global_positive_prompt": "", "global_negative_prompt": "", "global_prompt_policy_source": "frozen_njr",
        **changes.pop("config", {}),
    }
    return make_pipeline_njr(
        positive_prompt="A ceramic teapot on a wooden table.", base_model=P.transformer.filename,
        sampler_name="Euler", steps=9, cfg_scale=1, width=1024, height=1024, seed=424254,
        stage_chain=(make_stage_config("txt2img", model=P.transformer.filename, steps=9, cfg_scale=1,
                                       sampler_name="Euler", scheduler="Beta"),),
        config=data, backend_options={"image": {"backend_id": "forge_webui", "model_profile": P.reference()}},
        **changes,
    )


def transport(**kwargs):
    t = FakeWebUITransport(flavor="forge", checkpoint=P.transformer.filename, seed=424254,
                          modules=[{"model_name": a.filename, "filename": "/data/" + a.filename} for a in P.modules], **kwargs)
    t.options.update(SAMPLING_OPTIONS)
    return t


def test_actual_post_and_history_use_the_exact_profile(tmp_path):
    t = transport()
    entry = run_njr_via_queue(njr(), _client(t), artifact_root=tmp_path)
    assert entry.status is JobStatus.COMPLETED, entry.error_message
    assert len(t.generation_calls) == 1
    payload = t.generation_calls[0][2]
    assert payload == {
        "prompt": "A ceramic teapot on a wooden table.", "negative_prompt": "", "seed": 424254,
        "steps": 9, "sampler_name": "Euler", "scheduler": "Beta", "cfg_scale": 1,
        "distilled_cfg_scale": 9.0, "width": 1024, "height": 1024, "batch_size": 1, "n_iter": 1,
        "send_images": True, "save_images": False,
    }
    assert t.generation_module_state == [sorted(a.filename for a in P.modules)]
    snapshot = entry.snapshot["normalized_job"]
    assert snapshot["workload"]["backend_options"]["image"]["model_profile"] == P.reference()
    variant = entry.result["variants"][0]
    evidence = variant["image_backend_metadata"]["zimage_profile"]
    assert evidence["model_profile"] == P.reference() and evidence["family"] == "z_image"
    assert evidence["asset_identity"]["forge"]["revision"] == P.forge_revision
    assert evidence["requested_parameters"]["distilled_cfg_scale"] == 9
    assert evidence["qualification_status"].endswith("INSTRUMENTATION_GAP")
    image_path = Path(variant["artifact"]["primary_path"])
    manifest_path = Path(variant["artifact"]["manifest_path"])
    assert manifest_path == image_path.parent / "manifests" / f"{image_path.stem}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["zimage_effective_request"] == payload
    assert manifest["zimage_profile"]["model_profile"] == P.reference()
    assert manifest["zimage_profile"]["asset_identity"]["vae"]["sha256"] == P.vae.sha256
    assert manifest["zimage_selection"]["verified_before_dispatch"] is True


@pytest.mark.parametrize("change", [
    {"config": {"shift": 3}}, {"config": {"prompt_optimizer": {"enabled": True}}},
    {"config": {"global_positive_prompt": "extra"}}, {"config": {"enable_hr": True}},
    {"negative_prompt": "blurry"}, {"images_per_prompt": 2}, {"config": {"vae": "other"}},
])
def test_unsupported_immutable_work_fails_before_any_generation(change):
    t = transport()
    entry = run_njr_via_queue(njr(**change), _client(t))
    assert entry.status is JobStatus.FAILED
    assert not t.generation_calls


@pytest.mark.parametrize("change", [{"beta_dist_alpha": 0.9}, {"use_dynamic_shifting": True}])
def test_sampling_option_drift_is_refused_not_repaired(change):
    t = transport()
    t.options.update(change)
    entry = run_njr_via_queue(njr(), _client(t))
    assert entry.status is JobStatus.FAILED and not t.generation_calls
    for key, value in change.items():
        assert t.options[key] == value


def test_unconfirmed_modules_and_ambiguous_post_are_never_replayed():
    missing = transport(ignore_module_writes=True)
    entry = run_njr_via_queue(njr(), _client(missing))
    assert entry.status is JobStatus.FAILED and not missing.generation_calls
    ambiguous = transport(generation_error=requests.ReadTimeout("ambiguous response"))
    entry = run_njr_via_queue(njr(), _client(ambiguous))
    assert entry.status is JobStatus.FAILED
    assert len(ambiguous.generation_calls) == 1


def test_zimage_klein_and_sdxl_each_establish_their_own_module_baseline(monkeypatch):
    from src.image_backends.forge_klein_profile import KLEIN_PROFILE_V1
    from tests.integration.test_pr_img_116_klein_canonical_path import _t2i_njr

    monkeypatch.setattr("src.image_backends.forge_webui_backend.verify_klein_assets", lambda *a, **kw: {})
    t = transport()
    t.modules.extend({"model_name": a.filename, "filename": "/data/" + a.filename} for a in KLEIN_PROFILE_V1.modules)
    t.checkpoint_files.update({name: "/data/" + name for name in
                               (P.transformer.filename, KLEIN_PROFILE_V1.transformer.filename, "sdxl.safetensors")})
    for i, record in enumerate((njr(), _t2i_njr(), njr(), make_pipeline_njr(
            job_id="sdxl-baseline", base_model="sdxl.safetensors",
            backend_options={"image": {"backend_id": "forge_webui"}}), njr())):
        entry = run_njr_via_queue(record, _client(t))
        assert entry.status is JobStatus.COMPLETED, (i, entry.error_message)
    assert t.generation_module_state == [
        sorted(a.filename for a in P.modules), sorted(a.filename for a in KLEIN_PROFILE_V1.modules),
        sorted(a.filename for a in P.modules), [], sorted(a.filename for a in P.modules),
    ]


def test_wrong_asset_or_pin_refuses_before_module_write_or_generation(monkeypatch):
    from src.image_backends.forge_zimage_profile import ZImageProfileError

    def refuse(*args, **kwargs):
        raise ZImageProfileError("served hash or source pin mismatched")

    monkeypatch.setattr("src.image_backends.forge_webui_backend.verify_zimage_assets", refuse)
    t = transport()
    entry = run_njr_via_queue(njr(), _client(t))
    assert entry.status is JobStatus.FAILED and not t.generation_calls
    assert not [b for m, p, b in t.calls if m == "POST" and p == "/sdapi/v1/options"]
