"""PR-IMG-116: FLUX.2 Klein 4B FP8 through the canonical path with Forge-shaped HTTP (fakes only).

``NJR -> JobService -> SQLite -> PipelineRunner.run_njr -> ForgeWebUIImageBackend -> executor ->
ForgeWebUIClient``. Only ``requests.Session.request`` and the host-memory probe are replaced, so no
WebUI, model or GPU is used. These are deterministic stand-ins for the physical smokes.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import requests
from PIL import Image

import src.image_backends.forge_webui_backend as forge_backend_module
from src.api.forge_client import ForgeWebUIClient
from src.image_backends.forge_klein_profile import (
    KLEIN_EDIT_METADATA_KEY,
    KLEIN_PROFILE_ID,
    apply_klein_compile_policy,
    klein_edit_config,
)
from src.image_backends.forge_klein_readiness import HostMemorySnapshot
from src.pipeline.reprocess_builder import ReprocessJobBuilder, ReprocessSourceItem
from src.queue.job_model import JobStatus
from tests.helpers.fake_webui_transport import FakeWebUITransport
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config
from tests.helpers.njr_queue_harness import run_njr_via_queue

KLEIN = "flux-2-klein-4b-fp8.safetensors"
MODULES = [
    {"model_name": "qwen_3_4b.safetensors", "filename": "/data/models/text_encoder/qwen_3_4b.safetensors"},
    {"model_name": "flux2-vae.safetensors", "filename": "/data/models/VAE/flux2-vae.safetensors"},
    {"model_name": "sdxl_vae.safetensors", "filename": "/data/models/VAE/sdxl_vae.safetensors"},
]
PROFILE = {"id": KLEIN_PROFILE_ID, "version": 1}


@pytest.fixture(autouse=True)
def _qualified_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        forge_backend_module,
        "read_host_memory",
        lambda: HostMemorySnapshot(total_bytes=34_107_092_992, available_bytes=17_000_000_000),
    )
    # The configured backend is an explicit, non-default operator setting.
    monkeypatch.setattr("src.pipeline.klein_edit_reprocess.configured_image_backend_id", lambda: "forge_webui")
    monkeypatch.setattr("src.image_backends.image_backend_types.configured_image_backend_id", lambda: "forge_webui")


def _client(transport: FakeWebUITransport) -> ForgeWebUIClient:
    client = ForgeWebUIClient(base_url="http://127.0.0.1:7861", options_write_enabled=True)
    client._session.request = transport  # type: ignore[method-assign]
    client._options_min_interval_seconds = 0.0
    return client


def _transport() -> FakeWebUITransport:
    return FakeWebUITransport(flavor="forge", checkpoint=KLEIN, modules=MODULES)


def _t2i_njr(*, backend_id: str = "forge_webui", profile: dict | None = PROFILE, **overrides):
    image = {"backend_id": backend_id}
    if profile is not None:
        image["model_profile"] = profile
    base = {
        "model": KLEIN, "prompt": "portrait", "sampler_name": "Euler", "scheduler": "Beta", "steps": 4,
        "cfg_scale": 1.0, "width": 768, "height": 1024, "negative_prompt": "",
        "prompt_optimizer": {"enabled": False},
        "pipeline": {"apply_global_negative_txt2img": False, "apply_global_positive_txt2img": False},
        "global_positive_prompt": "", "global_negative_prompt": "", "global_prompt_policy_source": "frozen_njr",
    }
    config = {**base, **overrides.pop("config", {})}
    return make_pipeline_njr(
        job_id=overrides.pop("job_id", "klein-t2i"),
        positive_prompt="portrait of an adult on a rainy street",
        negative_prompt=overrides.pop("negative_prompt", ""),
        base_model=KLEIN,
        sampler_name=config["sampler_name"],
        steps=config["steps"],
        cfg_scale=config["cfg_scale"],
        width=config["width"],
        height=config["height"],
        seed=424242,
        stage_chain=overrides.pop(
            "stage_chain",
            (make_stage_config("txt2img", steps=config["steps"], cfg_scale=config["cfg_scale"],
                               sampler_name=config["sampler_name"], scheduler=config["scheduler"], model=KLEIN),),
        ),
        config=config,
        backend_options={"image": image},
        **overrides,
    )


def _run(njr, transport):
    return run_njr_via_queue(njr, _client(transport), timeout_seconds=60.0)


def _option_writes(transport):
    return [b for v, p, b in transport.calls if v == "POST" and p == "/sdapi/v1/options"]


def test_modules_are_applied_even_when_a_model_switch_just_consumed_the_options_throttle() -> None:
    """Smoke A found Forge loading Klein with no modules: the model-switch /options POST throttled the module POST."""

    import time

    transport = _transport()
    client = _client(transport)
    client._options_min_interval_seconds = 0.6
    client._last_options_post_ts = time.monotonic()  # an /options write (the model switch) happened an instant ago
    entry = run_njr_via_queue(_t2i_njr(job_id="klein-throttle"), client, timeout_seconds=60.0)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    assert sorted(m.rsplit("/", 1)[-1] for m in transport.options["forge_additional_modules"]) == [
        "flux2-vae.safetensors", "qwen_3_4b.safetensors"]
    assert [p for _, p, _ in transport.generation_calls] == ["/sdapi/v1/txt2img"]  # generation only after the modules


def test_an_unconfirmed_module_selection_never_reaches_generation() -> None:
    transport = _transport()
    client = _client(transport)
    client.set_additional_modules = lambda _modules: False  # type: ignore[method-assign]
    entry = run_njr_via_queue(_t2i_njr(job_id="klein-unconfirmed"), client, timeout_seconds=60.0)
    assert entry.status is JobStatus.FAILED
    assert transport.generation_calls == []


def test_klein_t2i_dispatches_once_with_exact_modules_and_fixed_semantics() -> None:
    transport = _transport()
    entry = _run(_t2i_njr(), transport)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    assert [p for _, p, _ in transport.generation_calls] == ["/sdapi/v1/txt2img"]
    payload = transport.payloads["/sdapi/v1/txt2img"][0]
    assert (payload["sampler_name"], payload["scheduler"], payload["steps"], payload["cfg_scale"]) == ("Euler", "Beta", 4, 1.0)
    assert (payload["width"], payload["height"], payload["seed"]) == (768, 1024, 424242)
    assert payload["negative_prompt"] == ""
    assert "ImageStitch Integrated" not in str(payload.get("alwayson_scripts", {}))
    # the complete module set was written once, in one POST, and verified
    writes = [w for w in _option_writes(transport) if "forge_additional_modules" in w]
    assert writes == [{"forge_additional_modules": ["qwen_3_4b.safetensors", "flux2-vae.safetensors"]}]
    assert sorted(m.rsplit("/", 1)[-1] for m in transport.options["forge_additional_modules"]) == [
        "flux2-vae.safetensors", "qwen_3_4b.safetensors"]
    # durable evidence + profile persisted in the immutable snapshot
    snapshot = (entry.snapshot or {}).get("normalized_job", {})
    assert snapshot["workload"]["backend_options"]["image"]["model_profile"] == PROFILE
    evidence = ((entry.result or {}).get("variants") or [{}])[0].get("image_backend_metadata", {}).get("klein_profile", {})
    assert evidence["model_profile"] == PROFILE and evidence["mode"] == "txt2img"
    assert evidence["transformer"]["sha256"].startswith("97ed34fe")
    assert [m["name"] for m in evidence["modules"]] == ["qwen_3_4b.safetensors", "flux2-vae.safetensors"]
    assert evidence["host_memory_before_dispatch"]["total_physical_gb"] > 34
    assert evidence["observed"]["modules"] is not None


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"config": {"steps": 30}}, "steps 30 conflicts"),
        ({"config": {"cfg_scale": 7.0}}, "CFG 7.0 conflicts"),
        ({"config": {"sampler_name": "DPM++ 2M"}}, "sampler 'DPM++ 2M' conflicts"),
        ({"config": {"width": 832, "height": 1216}}, "geometry 832x1216 is not qualified"),
        ({"negative_prompt": "blurry"}, "negative prompt"),
        ({"config": {"enable_hr": True}}, "hires fix"),
        ({"config": {"prompt_optimizer": {"enabled": True}}}, "prompt optimizer"),
        ({"config": {"global_negative_prompt": "nsfw"}}, "global negative prompt terms"),
        ({"config": {"vae": "sdxl_vae.safetensors"}}, "VAE 'sdxl_vae.safetensors'"),
        ({"stage_chain": (
            make_stage_config("txt2img", steps=4, cfg_scale=1.0, sampler_name="Euler", scheduler="Beta", model=KLEIN),
            make_stage_config("adetailer", model=KLEIN),
        )}, "stage chain"),
        ({"stage_chain": (
            make_stage_config("txt2img", steps=4, cfg_scale=1.0, sampler_name="Euler", scheduler="Beta", model=KLEIN),
            make_stage_config("upscale", model=KLEIN),
        )}, "stage chain"),
    ],
)
def test_conflicting_klein_work_fails_before_any_runtime_call_or_generation(override: dict, fragment: str) -> None:
    transport = _transport()
    entry = _run(_t2i_njr(**override), transport)

    assert entry.status is JobStatus.FAILED
    assert fragment in str(entry.error_message)
    assert transport.generation_calls == []
    assert _option_writes(transport) == []  # nothing was selected or changed on the endpoint


def test_a1111_with_a_klein_profile_is_rejected_and_never_switched() -> None:
    transport = FakeWebUITransport(flavor="a1111", checkpoint=KLEIN)
    client = ForgeWebUIClient  # transport shape irrelevant: validation precedes every call
    del client
    from src.api.client import SDWebUIClient

    a1111 = SDWebUIClient(base_url="http://127.0.0.1:7860", options_write_enabled=True)
    a1111._session.request = transport  # type: ignore[method-assign]
    entry = run_njr_via_queue(_t2i_njr(backend_id="a1111_webui"), a1111, timeout_seconds=60.0)
    assert entry.status is JobStatus.FAILED
    assert "requires the 'forge_webui' backend" in str(entry.error_message)
    assert transport.generation_calls == []


def test_host_ram_below_the_qualified_class_fails_before_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        forge_backend_module,
        "read_host_memory",
        lambda: HostMemorySnapshot(total_bytes=17_000_000_000, available_bytes=9_000_000_000),
    )
    transport = _transport()
    entry = _run(_t2i_njr(), transport)
    assert entry.status is JobStatus.FAILED
    assert "32-GB-class host" in str(entry.error_message)
    assert transport.generation_calls == []
    assert not any("forge_additional_modules" in w for w in _option_writes(transport))


def test_low_available_ram_is_recorded_but_never_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        forge_backend_module,
        "read_host_memory",
        lambda: HostMemorySnapshot(total_bytes=34_107_092_992, available_bytes=500_000_000),
    )
    entry = _run(_t2i_njr(job_id="klein-lowram"), _transport())
    assert entry.status is JobStatus.COMPLETED, entry.error_message
    evidence = ((entry.result or {}).get("variants") or [{}])[0]["image_backend_metadata"]["klein_profile"]
    assert evidence["host_memory_before_dispatch"]["available_physical_gb"] == 0.5
    assert "warnings" not in evidence["host_memory_before_dispatch"]


def test_an_unavailable_module_fails_before_generation() -> None:
    transport = FakeWebUITransport(flavor="forge", checkpoint=KLEIN, modules=MODULES[:1])  # no flux2-vae
    entry = _run(_t2i_njr(job_id="klein-nomodule"), transport)
    assert entry.status is JobStatus.FAILED
    assert "does not list the required module(s)" in str(entry.error_message)
    assert "install_forge_klein_assets.ps1" in str(entry.error_message)
    assert transport.generation_calls == []


def test_normal_forge_sdxl_work_is_unaffected_by_the_klein_support() -> None:
    sdxl_modules = [{"model_name": "sdxl_vae.safetensors", "filename": "/models/VAE/sdxl_vae.safetensors"}]
    transport = FakeWebUITransport(flavor="forge", modules=sdxl_modules)
    njr = make_pipeline_njr(
        job_id="sdxl-forge", positive_prompt="a lighthouse", negative_prompt="lowres", base_model="sdxl.safetensors",
        sampler_name="Euler a", steps=24, cfg_scale=5.5, width=832, height=1216, seed=7,
        stage_chain=(make_stage_config("txt2img", steps=24, cfg_scale=5.5, sampler_name="Euler a",
                                       scheduler="Karras", model="sdxl.safetensors", vae="sdxl_vae.safetensors"),),
        config={"model": "sdxl.safetensors", "vae": "sdxl_vae.safetensors", "prompt": "a lighthouse",
                "sampler_name": "Euler a", "scheduler": "Karras", "steps": 24, "cfg_scale": 5.5,
                "width": 832, "height": 1216},
        backend_options={"image": {"backend_id": "forge_webui"}},
    )
    entry = _run(njr, transport)
    assert entry.status is JobStatus.COMPLETED, entry.error_message
    payload = transport.payloads["/sdapi/v1/txt2img"][0]
    assert (payload["steps"], payload["cfg_scale"], payload["sampler_name"]) == (24, 5.5, "Euler a")
    assert "lowres" in payload["negative_prompt"]
    assert {"forge_additional_modules": ["sdxl_vae.safetensors"]} in _option_writes(transport)
    meta = ((entry.result or {}).get("variants") or [{}])[0].get("image_backend_metadata", {})
    assert "klein_profile" not in meta


# --------------------------------------------------------------------------- single-reference edit


def _source_png(tmp_path: Path, size: tuple[int, int] = (768, 1024)) -> Path:
    path = tmp_path / "klein_source.png"
    Image.new("RGB", size, (90, 120, 60)).save(path)
    return path


def _edit_njr(tmp_path: Path, **kwargs):
    source = kwargs.pop("source", None) or _source_png(tmp_path)
    plan = ReprocessJobBuilder().build_grouped_reprocess_jobs(
        items=[ReprocessSourceItem(
            input_image_path=str(source),
            prompt="keep everything; change only the jacket to deep red leather",
            metadata={KLEIN_EDIT_METADATA_KEY: True, "parent_job_id": "parent-A", "parent_artifact_id": "art-A"},
        )],
        stages=kwargs.pop("stages", ["img2img"]),
        fallback_config={},
        batch_size=kwargs.pop("batch_size", 5),
        pack_name="ReviewReprocess",
        source="review_tab",
        output_dir=str(tmp_path / "out"),
        # the Review controller supplies the parent lineage block the same way
        extra_metadata_builder=lambda _chunk, _dir: {"parent_job_id": "parent-A", "parent_artifact_id": "art-A"},
    )
    assert len(plan.jobs) == 1
    return plan.jobs[0], source


def test_review_klein_edit_is_one_img2img_nje_with_one_reference_and_lineage(tmp_path: Path) -> None:
    njr, source = _edit_njr(tmp_path)
    assert [s.stage_type for s in njr.stages] == ["img2img"]
    assert njr.input_image_paths == (str(source),)
    assert njr.backend_options["image"] == {"model_profile": PROFILE, "backend_id": "forge_webui"}
    lineage = njr.provenance.metadata["reprocess"]["source_items"][0]["metadata"]
    assert lineage["parent_job_id"] == "parent-A"
    assert lineage[KLEIN_EDIT_METADATA_KEY]["source_image_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert njr.source.parent_job_id == "parent-A"

    transport = _transport()
    entry = _run(njr, transport)

    assert entry.status is JobStatus.COMPLETED, entry.error_message
    assert [p for _, p, _ in transport.generation_calls] == ["/sdapi/v1/img2img"]
    payload = transport.payloads["/sdapi/v1/img2img"][0]
    assert len(payload["init_images"]) == 1
    assert payload["denoising_strength"] == 1.0
    assert (payload["sampler_name"], payload["scheduler"], payload["steps"], payload["cfg_scale"]) == ("Euler", "Beta", 4, 1.0)
    assert (payload["width"], payload["height"]) == (768, 1024)
    assert payload["negative_prompt"] == ""
    assert "alwayson_scripts" not in payload  # no ImageStitch / multi-reference
    assert "jacket" in payload["prompt"]
    evidence = ((entry.result or {}).get("variants") or [{}])[0]["image_backend_metadata"]["klein_profile"]
    assert evidence["mode"] == "single_reference_edit"
    assert evidence["source_image"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()


def test_an_arbitrary_review_image_needs_the_explicit_klein_selection(tmp_path: Path) -> None:
    source = _source_png(tmp_path)
    item = ReprocessSourceItem(input_image_path=str(source), prompt="make it red", model="flux-2-klein-4b-fp8.safetensors")
    plan = ReprocessJobBuilder().build_grouped_reprocess_jobs(
        items=[item], stages=["img2img"], fallback_config={}, batch_size=1, output_dir=str(tmp_path / "out")
    )
    # a Klein-looking name alone is not enough: no explicit selection -> no profile, no Klein freeze
    assert "model_profile" not in plan.jobs[0].backend_options.get("image", {})
    assert plan.jobs[0].sampler_name != "Euler" or plan.jobs[0].steps != 4


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"stages": ["img2img", "adetailer"]}, "stage chain"),
        ({"stages": ["adetailer"]}, "stage chain"),
        ({"stages": ["img2img", "upscale"]}, "stage chain"),
    ],
)
def test_klein_edit_rejects_extra_stages_before_anything_is_built(tmp_path: Path, kwargs: dict, fragment: str) -> None:
    with pytest.raises(ValueError, match=fragment):
        _edit_njr(tmp_path, **kwargs)


def test_klein_edit_rejects_unqualified_source_geometry(tmp_path: Path) -> None:
    source = _source_png(tmp_path, size=(832, 1216))
    with pytest.raises(ValueError, match="geometry 832x1216 is not qualified"):
        _edit_njr(tmp_path, source=source)


def test_klein_edit_on_a_a1111_configuration_is_an_actionable_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.pipeline.klein_edit_reprocess.configured_image_backend_id", lambda: "a1111_webui")
    with pytest.raises(ValueError, match="never switches the configured backend"):
        _edit_njr(tmp_path)


def test_klein_edit_never_batches_several_images_into_one_job(tmp_path: Path) -> None:
    a, b = _source_png(tmp_path), tmp_path / "second.png"
    Image.new("RGB", (768, 1024)).save(b)
    plan = ReprocessJobBuilder().build_grouped_reprocess_jobs(
        items=[ReprocessSourceItem(input_image_path=str(p), prompt="edit", metadata={KLEIN_EDIT_METADATA_KEY: True}) for p in (a, b)],
        stages=["img2img"], fallback_config={}, batch_size=10, output_dir=str(tmp_path / "out"),
    )
    assert [len(j.input_image_paths) for j in plan.jobs] == [1, 1]


def test_a_klein_edit_job_with_two_source_images_is_rejected_before_dispatch(tmp_path: Path) -> None:
    njr, source = _edit_njr(tmp_path)
    other = tmp_path / "other.png"
    Image.new("RGB", (768, 1024)).save(other)
    from dataclasses import replace

    two = replace(njr, workload=replace(njr.workload, input_image_paths=(str(source), str(other))))
    transport = _transport()
    entry = _run(two, transport)
    assert entry.status is JobStatus.FAILED
    assert "exactly 1 source image" in str(entry.error_message)
    assert transport.generation_calls == []


def test_failed_dispatch_is_never_retried_or_replayed_automatically(tmp_path: Path) -> None:
    # the response is lost after the POST was sent: the repository's existing guard refuses replay
    transport = FakeWebUITransport(
        flavor="forge", checkpoint=KLEIN, modules=MODULES, generation_error=requests.ConnectionError("lost")
    )
    entry = _run(_t2i_njr(job_id="klein-noretry"), transport)
    assert entry.status is JobStatus.FAILED
    assert len(transport.generation_calls) == 1  # exactly one dispatch, no replay, no backend fallback


def test_compile_policy_output_passes_the_runner_validation() -> None:
    config = apply_klein_compile_policy(
        {"txt2img": {"model": KLEIN, "steps": 20, "cfg_scale": 7.0, "sampler_name": "Euler a", "width": 1024, "height": 1024}}
    )
    assert config["txt2img"]["steps"] == 4
    assert klein_edit_config(width=1024, height=1024)["width"] == 1024
