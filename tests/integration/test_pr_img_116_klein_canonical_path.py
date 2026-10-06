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
PROFILE = {"id": KLEIN_PROFILE_ID, "version": 1}  # an explicit, persisted v1 reference
#: what newly constructed work is stamped with since PR-IMG-117 (v1 records keep meaning exactly v1)
PROFILE_NEW = {"id": KLEIN_PROFILE_ID, "version": 2}
_STUB_IDENTITY = {"transformer": {"name": KLEIN, "verified": "sha256"}}


@pytest.fixture(autouse=True)
def _qualified_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        forge_backend_module,
        "read_host_memory",
        lambda: HostMemorySnapshot(total_bytes=34_107_092_992, available_bytes=17_000_000_000),
    )
    # The byte-level asset identity is proven by dedicated tests; here it is stubbed (12 GB are never hashed).
    monkeypatch.setattr(forge_backend_module, "verify_klein_assets", lambda profile, **_k: _STUB_IDENTITY)
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
    assert njr.backend_options["image"] == {"model_profile": PROFILE_NEW, "backend_id": "forge_webui"}
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
    # The explicit selection is what freezes the Klein edit (fixed sampling, one source, frozen source digest) ...
    job = plan.jobs[0]
    assert job.sampler_name != "Euler" or job.steps != 4
    assert KLEIN_EDIT_METADATA_KEY not in job.provenance.metadata["reprocess"]["source_items"][0]["metadata"]
    # ... but the qualified model never silently becomes unrestricted Forge work: the profile is preserved.
    assert job.backend_options["image"]["model_profile"] == PROFILE_NEW


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


# --------------------------------------------------------------------------- review repair: bytes, not names


@pytest.fixture
def real_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Real byte-level verification against tiny stand-in assets, bound to a (fake) StableNew-owned launch session."""

    import src.image_backends.forge_klein_assets as assets_module
    import src.image_backends.forge_klein_profile as profile_module
    from tests.image_backends.test_forge_klein_assets import (
        install,
        owned_manager,
        tiny_profile,
        use_manager,
    )

    profile = tiny_profile()
    monkeypatch.setitem(profile_module._PROFILES, (KLEIN_PROFILE_ID, 1), profile)
    data_dir = tmp_path / "forge-data"
    install(data_dir, profile)
    assets_module.clear_verified_cache()
    monkeypatch.setattr(forge_backend_module, "verify_klein_assets", assets_module.verify_klein_assets)  # undo the stub
    use_manager(monkeypatch, owned_manager(data_dir, endpoint="http://127.0.0.1:7861"))
    yield profile, data_dir
    assets_module.clear_verified_cache()


def test_exact_installed_files_dispatch_and_the_observed_identity_is_recorded(real_identity) -> None:
    profile, _ = real_identity
    transport = _transport()
    entry = _run(_t2i_njr(job_id="klein-bytes-ok"), transport)
    assert entry.status is JobStatus.COMPLETED, entry.error_message
    evidence = ((entry.result or {}).get("variants") or [{}])[0]["image_backend_metadata"]["klein_profile"]
    assert {r: e["sha256"] for r, e in evidence["asset_identity"].items()} == {a.role: a.sha256 for a in profile.assets}
    assert len(transport.generation_calls) == 1


def test_same_name_wrong_bytes_fail_before_any_runtime_write_or_generation(real_identity) -> None:
    profile, data_dir = real_identity
    (data_dir / "models" / "VAE" / profile.vae.filename).write_bytes(b"x" * profile.vae.size)
    transport = _transport()  # Forge's API happily lists the right NAMES
    entry = _run(_t2i_njr(job_id="klein-bytes-wrong"), transport)
    assert entry.status is JobStatus.FAILED and "SHA-256" in str(entry.error_message)
    assert transport.generation_calls == [] and _option_writes(transport) == []


def test_a_file_mutated_after_a_verified_job_fails_the_next_job_before_dispatch(real_identity) -> None:
    import os

    profile, data_dir = real_identity
    transport = _transport()
    client = _client(transport)
    first = run_njr_via_queue(_t2i_njr(job_id="klein-mut-1"), client, timeout_seconds=60.0)
    assert first.status is JobStatus.COMPLETED, first.error_message
    target = data_dir / "models" / "text_encoder" / profile.text_encoder.filename
    stat = target.stat()
    target.write_bytes(b"q" * profile.text_encoder.size)
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000))
    second = run_njr_via_queue(_t2i_njr(job_id="klein-mut-2"), client, timeout_seconds=60.0)
    assert second.status is JobStatus.FAILED and "SHA-256" in str(second.error_message)
    assert len(transport.generation_calls) == 1  # only the first job ever dispatched


def test_an_unverifiable_runtime_fails_closed_without_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.image_backends.forge_klein_profile import KleinProfileError

    def unverifiable(_profile, **_kwargs):
        raise KleinProfileError("the identity of the Klein model files cannot be established")

    monkeypatch.setattr(forge_backend_module, "verify_klein_assets", unverifiable)
    transport = _transport()
    entry = _run(_t2i_njr(job_id="klein-unverifiable"), transport)
    assert entry.status is JobStatus.FAILED and "cannot be established" in str(entry.error_message)
    assert transport.generation_calls == []


# --------------------------------------------------------------------------- review repair: frozen source


def test_an_unchanged_source_passes_the_frozen_digest_check(tmp_path: Path) -> None:
    njr, source = _edit_njr(tmp_path)
    entry = _run(njr, _transport())
    assert entry.status is JobStatus.COMPLETED, entry.error_message
    evidence = ((entry.result or {}).get("variants") or [{}])[0]["image_backend_metadata"]["klein_profile"]
    assert evidence["source_image"]["verified_before_dispatch"] is True
    assert evidence["source_image"]["sha256"] == evidence["source_image"]["frozen_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()


def test_a_source_mutated_after_admission_fails_before_the_generation_post(tmp_path: Path) -> None:
    njr, source = _edit_njr(tmp_path)
    Image.new("RGB", (768, 1024), (1, 2, 3)).save(source)  # same size, different pixels, after admission
    transport = _transport()
    entry = _run(njr, transport)
    assert entry.status is JobStatus.FAILED and "changed after the job was admitted" in str(entry.error_message)
    assert transport.generation_calls == []
    # the frozen digest is never refreshed: the immutable NJR still carries the admission-time value
    frozen = njr.provenance.metadata["reprocess"]["source_items"][0]["metadata"][KLEIN_EDIT_METADATA_KEY]["source_image_sha256"]
    assert frozen != hashlib.sha256(source.read_bytes()).hexdigest()


def test_a_missing_source_fails_before_the_generation_post(tmp_path: Path) -> None:
    njr, source = _edit_njr(tmp_path)
    source.unlink()
    transport = _transport()
    entry = _run(njr, transport)
    assert entry.status is JobStatus.FAILED
    assert transport.generation_calls == []


def test_an_edit_without_a_frozen_digest_is_refused() -> None:
    from types import SimpleNamespace

    from src.image_backends.forge_klein_profile import KleinProfileError
    from src.image_backends.forge_webui_backend import ForgeWebUIImageBackend

    request = SimpleNamespace(input_image_path=Path("x.png"), context_metadata={"provenance": {"reprocess": {"source_items": []}}})
    with pytest.raises(KleinProfileError, match="frozen SHA-256"):
        ForgeWebUIImageBackend._verify_frozen_source(request)  # type: ignore[arg-type]


def test_klein_on_an_external_forge_fails_before_any_runtime_write_or_generation(real_identity, monkeypatch: pytest.MonkeyPatch) -> None:
    """A positively identified Forge that StableNew does not own is rejected, for Klein only."""

    from tests.image_backends.test_forge_klein_assets import owned_manager, use_manager

    use_manager(monkeypatch, owned_manager(None, owns=False))
    transport = _transport()  # its API happily reports Forge and the right names
    entry = _run(_t2i_njr(job_id="klein-external"), transport)
    assert entry.status is JobStatus.FAILED and "requires the StableNew-owned managed Forge" in str(entry.error_message)
    assert transport.generation_calls == [] and _option_writes(transport) == []


def test_klein_with_a_manager_serving_another_endpoint_fails_closed(real_identity, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.image_backends.test_forge_klein_assets import owned_manager, use_manager

    _profile, data_dir = real_identity
    use_manager(monkeypatch, owned_manager(data_dir, endpoint="http://127.0.0.1:9999"))
    transport = _transport()
    entry = _run(_t2i_njr(job_id="klein-endpoint"), transport)
    assert entry.status is JobStatus.FAILED and "not the client endpoint" in str(entry.error_message)
    assert transport.generation_calls == []


def test_ordinary_forge_work_is_unchanged_when_no_owned_manager_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    """External Forge remains fully supported for everything except the qualified Klein profile."""

    monkeypatch.setattr("src.image_backends.forge_klein_assets._active_manager", lambda: None)
    sdxl_modules = [{"model_name": "sdxl_vae.safetensors", "filename": "/models/VAE/sdxl_vae.safetensors"}]
    transport = FakeWebUITransport(flavor="forge", modules=sdxl_modules)
    njr = make_pipeline_njr(
        job_id="sdxl-external", positive_prompt="a lighthouse", negative_prompt="lowres", base_model="sdxl.safetensors",
        sampler_name="Euler a", steps=24, cfg_scale=5.5, width=832, height=1216, seed=7,
        stage_chain=(make_stage_config("txt2img", steps=24, cfg_scale=5.5, sampler_name="Euler a", scheduler="Karras",
                                       model="sdxl.safetensors", vae="sdxl_vae.safetensors"),),
        config={"model": "sdxl.safetensors", "vae": "sdxl_vae.safetensors", "prompt": "a lighthouse", "sampler_name": "Euler a",
                "scheduler": "Karras", "steps": 24, "cfg_scale": 5.5, "width": 832, "height": 1216},
        backend_options={"image": {"backend_id": "forge_webui"}},
    )
    entry = _run(njr, transport)
    assert entry.status is JobStatus.COMPLETED, entry.error_message
    assert [p for _, p, _ in transport.generation_calls] == ["/sdapi/v1/txt2img"]


# --------------------------------------------------------------------------- closeout: profile survives reprocess construction


def _artifact_item(tmp_path: Path, *, model: str = KLEIN, prompt: str = "polish the face") -> tuple[ReprocessSourceItem, Path]:
    """What Review builds from an artifact: the model restored from embedded metadata, NO explicit Klein marker."""

    source = _source_png(tmp_path)
    return ReprocessSourceItem(input_image_path=str(source), prompt=prompt, model=model), source


def _review_default_njr(tmp_path: Path, stages: list[str], *, model: str = KLEIN):
    item, _ = _artifact_item(tmp_path, model=model)
    plan = ReprocessJobBuilder().build_grouped_reprocess_jobs(
        items=[item], stages=stages, fallback_config={}, batch_size=1, pack_name="ReviewReprocess",
        source="review_tab", output_dir=str(tmp_path / "out"),
    )
    assert len(plan.jobs) == 1
    return plan.jobs[0]


def test_build_reprocess_job_stamps_the_profile_from_the_resolved_klein_model(tmp_path: Path) -> None:
    source = _source_png(tmp_path)
    njr = ReprocessJobBuilder().build_reprocess_job([source], ["adetailer"], model=KLEIN, output_dir=str(tmp_path / "out"))
    assert njr.backend_options["image"]["model_profile"] == {"id": "flux2_klein_4b_fp8", "version": 2}
    assert njr.backend_options["image"]["backend_id"] == "forge_webui"


@pytest.mark.parametrize("stages", [["adetailer"], ["upscale"], ["img2img", "adetailer"]])
def test_review_default_reprocess_of_a_klein_artifact_keeps_the_profile_and_fails_before_dispatch(tmp_path: Path, stages: list[str]) -> None:
    njr = _review_default_njr(tmp_path, stages)
    assert njr.backend_options["image"]["model_profile"] == {"id": "flux2_klein_4b_fp8", "version": 2}
    transport = _transport()
    entry = _run(njr, transport)
    assert entry.status is JobStatus.FAILED and "FLUX.2 Klein 4B FP8" in str(entry.error_message)
    assert transport.generation_calls == [] and _option_writes(transport) == []  # no generation, no options mutation


def test_an_unmarked_klein_img2img_cannot_bypass_the_profile_validation(tmp_path: Path) -> None:
    njr = _review_default_njr(tmp_path, ["img2img"])
    assert njr.backend_options["image"]["model_profile"]["id"] == "flux2_klein_4b_fp8"  # not silently unrestricted Forge work
    transport = _transport()
    entry = _run(njr, transport)
    assert entry.status is JobStatus.FAILED and "FLUX.2 Klein 4B FP8" in str(entry.error_message)
    assert transport.generation_calls == [] and _option_writes(transport) == []


def test_an_unmarked_klein_img2img_without_a_frozen_source_digest_is_refused_even_if_the_envelope_matches(tmp_path: Path) -> None:
    """Even with every sampling field coincidentally in range, only the explicit edit path freezes the source digest."""

    item, _ = _artifact_item(tmp_path)
    item.config = klein_edit_config(width=768, height=1024)  # envelope-conforming config, but no Klein edit marker
    plan = ReprocessJobBuilder().build_grouped_reprocess_jobs(
        items=[item], stages=["img2img"], fallback_config={}, batch_size=1, output_dir=str(tmp_path / "out"))
    transport = _transport()
    entry = _run(plan.jobs[0], transport)
    assert entry.status is JobStatus.FAILED
    assert "frozen SHA-256" in str(entry.error_message) or "FLUX.2 Klein 4B FP8" in str(entry.error_message)
    assert transport.generation_calls == []


def test_the_explicit_klein_edit_path_is_unchanged_and_still_valid(tmp_path: Path) -> None:
    njr, _source = _edit_njr(tmp_path)
    assert njr.backend_options["image"]["model_profile"] == PROFILE_NEW
    entry = _run(njr, _transport())
    assert entry.status is JobStatus.COMPLETED, entry.error_message


def test_sdxl_reprocess_receives_no_klein_profile_and_still_runs(tmp_path: Path) -> None:
    sdxl_modules = [{"model_name": "sdxl_vae.safetensors", "filename": "/models/VAE/sdxl_vae.safetensors"}]
    njr = _review_default_njr(tmp_path, ["img2img"], model="sdxl.safetensors")
    assert njr.backend_options["image"] == {"backend_id": "forge_webui"}  # exactly as before: no profile key
    transport = FakeWebUITransport(flavor="forge", modules=sdxl_modules)
    entry = _run(njr, transport)
    assert entry.status is JobStatus.COMPLETED, entry.error_message
    assert [p for _, p, _ in transport.generation_calls] == ["/sdapi/v1/img2img"]
    assert "klein_profile" not in str(((entry.result or {}).get("variants") or [{}])[0].get("image_backend_metadata", {}))
    for stages in (["adetailer"], ["upscale"]):
        assert "model_profile" not in _review_default_njr(tmp_path, stages, model="sdxl.safetensors").backend_options["image"]


def test_a_klein_model_on_a1111_keeps_its_profile_and_is_rejected_not_rerouted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.api.client import SDWebUIClient

    monkeypatch.setattr("src.image_backends.image_backend_types.configured_image_backend_id", lambda: "a1111_webui")
    njr = _review_default_njr(tmp_path, ["img2img"])
    assert njr.backend_options["image"] == {"backend_id": "a1111_webui", "model_profile": PROFILE_NEW}  # profile preserved, backend not switched
    transport = FakeWebUITransport(flavor="a1111", checkpoint=KLEIN)
    a1111 = SDWebUIClient(base_url="http://127.0.0.1:7860", options_write_enabled=True)
    a1111._session.request = transport  # type: ignore[method-assign]
    entry = run_njr_via_queue(njr, a1111, timeout_seconds=60.0)
    assert entry.status is JobStatus.FAILED and "requires the 'forge_webui' backend" in str(entry.error_message)
    assert transport.generation_calls == []
