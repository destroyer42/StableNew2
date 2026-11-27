"""RG-140 slice 2 compiles: another model, aspect ratio, prompt tweak, Make Video and multi-stage "more like this".

Hermetic: the application compiler against a recording host; the host against the real Review img2img and outpaint
compilers on temporary images (snapshot root and family lookup redirected to the test); Make Video against the real
workflow catalog and NJR builder in a temporary Output folder. Nothing is admitted and no backend is called.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from src.app import site_phone_followup
from src.app.review_gateway_actions import (
    ASPECT_RATIOS,
    ActionRefused,
    AppActionCompiler,
    model_choice_id,
)
from src.app.review_gateway_protocol import ActionInput
from src.app.site_media_files import SiteOutputError
from src.app.site_phone_admission import PhonePreviewInput
from src.pipeline.job_models_v2 import WorkloadKind
from tests.helpers.job_helpers import make_test_njr
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config

JUGG = "C:\\Forge\\models\\Stable-diffusion\\juggernautXL.safetensors [a1b2c3]"
PONY = "ponyXL.safetensors"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Host:
    """Records what the application compiler asks of the preview host."""

    def __init__(self, *, size=(832, 1216), baseline=None) -> None:
        self.models: tuple[str, ...] = (PONY, JUGG)
        self.baseline = (
            baseline
            if baseline is not None
            else {"model": "juggernautXL.safetensors", "prompt": "a lighthouse at dusk"}
        )
        self.calls: list[tuple] = []
        self.job = make_test_njr(
            base_model="C:\\Forge\\models\\ponyXL.safetensors",
            config={"img2img": {"denoising_strength": 0.35, "width": 832, "height": 1248}},
        )
        self.size = size

    def gateway_models(self):
        return self.models

    def image_baseline(self, path):
        return dict(self.baseline)

    def compile_gateway_img2img(self, path, digest, *, model=None, prompt_add=""):
        self.calls.append(("img2img", model, prompt_add))
        return PhonePreviewInput(path.name, (self.job,), lambda: None)

    def compile_gateway_outpaint(self, path, digest, *, ratio):
        self.calls.append(("outpaint", ratio))
        return PhonePreviewInput(path.name, (self.job,), lambda: None)


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "portrait.png"
    Image.new("RGB", (832, 1216), "#557733").save(path)
    return path


def _compiler(host, tmp_path, **options):
    return AppActionCompiler(host, repository=None, output_root=tmp_path, **options)


def test_the_checkpoint_list_names_files_never_paths_and_marks_the_images_own(tmp_path, image):
    listed = _compiler(Host(), tmp_path).choices("another_model", image, "d" * 64).payload()

    assert listed["items"] == [
        {
            "id": model_choice_id(JUGG),
            "label": "juggernautXL.safetensors [a1b2c3]",
            "current": True,
        },
        {"id": model_choice_id(PONY), "label": PONY},
    ]
    assert "Forge" not in str(listed)


def test_another_model_is_an_img2img_rework_through_the_chosen_checkpoint(tmp_path, image):
    host = Host()
    compiled = _compiler(host, tmp_path).compile(
        "another_model", image, "d" * 64, (), ActionInput(choice=model_choice_id(PONY))
    )

    assert host.calls == [("img2img", PONY, "")]
    assert compiled.reprocess and compiled.kind == "rework"
    assert compiled.lines[0] == (
        "img2img of this exact image through ponyXL.safetensors at denoise 0.35."
    )
    assert compiled.choices is not None and len(compiled.choices.items) == 2
    assert model_choice_id(PONY) in compiled.identity


@pytest.mark.parametrize(
    "choice, detail",
    [("not-listed", "choice_unavailable"), (model_choice_id(JUGG), "no_change")],
)
def test_another_model_refuses_an_unlisted_or_unchanged_checkpoint(tmp_path, image, choice, detail):
    host = Host()

    with pytest.raises(ActionRefused) as refused:
        _compiler(host, tmp_path).compile(
            "another_model", image, "d" * 64, (), ActionInput(choice=choice)
        )
    assert refused.value.detail == detail and host.calls == []


def test_no_checkpoints_is_a_closed_refusal(tmp_path, image):
    host = Host()
    host.models = ()

    with pytest.raises(ActionRefused) as refused:
        _compiler(host, tmp_path).choices("another_model", image, "d" * 64)
    assert refused.value.detail == "model_unavailable"


def test_aspect_ratios_mark_the_images_own_and_outpaint_to_the_chosen_one(tmp_path):
    square = tmp_path / "square.png"
    Image.new("RGB", (1024, 1024), "#335577").save(square)
    host = Host()
    compiler = _compiler(host, tmp_path)

    listed = compiler.choices("aspect_ratio", square, "d" * 64).payload()
    assert [item["id"] for item in listed["items"]] == [entry[0] for entry in ASPECT_RATIOS]
    assert [item["id"] for item in listed["items"] if item.get("current")] == ["1x1"]

    compiled = compiler.compile("aspect_ratio", square, "d" * 64, (), ActionInput(choice="2x3"))
    assert host.calls == [("outpaint", (2, 3))]
    assert compiled.lines[0].startswith("Extends the canvas to Portrait 2:3 (832 × 1248)")
    assert compiled.reprocess and compiled.kind == "rework"
    with pytest.raises(ActionRefused) as refused:
        compiler.compile("aspect_ratio", square, "d" * 64, (), ActionInput(choice="7x3"))
    assert refused.value.detail == "choice_unavailable"


def test_a_prompt_tweak_appends_one_line_of_words_through_img2img(tmp_path, image):
    host = Host()
    compiler = _compiler(host, tmp_path)

    compiled = compiler.compile(
        "prompt_tweak", image, "d" * 64, (), ActionInput(text="  smiling,\t golden hour ")
    )

    assert host.calls == [("img2img", None, "smiling, golden hour")]
    assert compiled.lines[0] == "Adds to the prompt: “smiling, golden hour”."
    with pytest.raises(ActionRefused) as refused:
        compiler.compile("prompt_tweak", image, "d" * 64, (), ActionInput(text="   "))
    assert refused.value.detail == "prompt_required"


def test_make_video_uses_the_owners_motion_prompt_or_the_images_own(tmp_path, image, monkeypatch):
    import src.video.workflow_frame_count as frames

    monkeypatch.setattr(frames, "frame_count_policy", lambda _spec: {"default": 81, "fps": 16})
    asked = []
    spec = SimpleNamespace(
        display_name="Wan2.2 I2V-A14B 4-step",
        registry_key=("wan22_i2v_a14b", "1.0.0"),
        backend_defaults={},
    )

    def video(root, path, digest, prompt, seed):
        asked.append((root, prompt, seed))
        job = make_test_njr()
        return spec, PhonePreviewInput(path.name, (job,), lambda: None)

    compiler = _compiler(Host(), tmp_path, video=video)
    own = compiler.compile("make_video", image, "d" * 64, (7,), ActionInput())
    words = compiler.compile(
        "make_video", image, "d" * 64, (8,), ActionInput(text="she turns to the window")
    )

    assert asked == [
        (tmp_path, "a lighthouse at dusk", 7),
        (tmp_path, "she turns to the window", 8),
    ]
    assert own.kind == "video" and not own.reprocess
    assert (
        own.lines[0]
        == "Wan2.2 I2V-A14B 4-step: a 81-frame clip from this image, about 5.1 s at 16 fps."
    )
    assert own.lines[1] == "Motion prompt: the image's own prompt."
    assert words.lines[1] == "Motion prompt: “she turns to the window”."
    assert own.identity != words.identity
    with pytest.raises(ActionRefused) as refused:
        _compiler(Host(baseline={}), tmp_path, video=video).compile(
            "make_video", image, "d" * 64, (9,), ActionInput()
        )
    assert refused.value.detail == "prompt_required"


# -- "more like this" of a whole recipe -----------------------------------------------------------------------------


def _multi_stage(job_id="parent-1"):
    return make_pipeline_njr(
        job_id=job_id,
        stage_chain=(make_stage_config("txt2img"), make_stage_config("adetailer")),
        config={"seed": 42, "txt2img": {"seed": 42}},
        extra_metadata={
            "batch": {"schema": "stablenew.batch.v1", "batch_id": "b-1", "name": "portraits"}
        },
        seed=42,
    )


def test_more_like_this_reruns_a_multi_stage_recipe_with_new_seeds(tmp_path, monkeypatch, image):
    def not_variable(*_args):
        raise SiteOutputError("followup_provenance_unverified")

    record = _multi_stage()
    monkeypatch.setattr(site_phone_followup, "verified_history_source", not_variable)
    monkeypatch.setattr(
        site_phone_followup, "verified_recipe_source", lambda *_args: (record, "fp-1")
    )
    compiler = AppActionCompiler(Host(), repository=Mock(), output_root=tmp_path)

    compiled = compiler.compile("more_like_this", image, _digest(image), (11, 12, 13))

    assert [job.seed for job in compiled.records] == [11, 12, 13]
    assert all(job.stage_chain_labels == ["txt2img", "adetailer"] for job in compiled.records)
    assert all(job.source.parent_job_id == "parent-1" for job in compiled.records)
    assert compiled.lines[:2] == (
        "3 new images, each with a new seed.",
        "Re-runs this image's whole recipe (txt2img → adetailer) with only the seed changed.",
    )
    assert compiled.identity[-1] == "recipe" and compiled.kind == "followup"
    compiled.require_current()


def test_a_recipe_that_cannot_be_reseeded_is_refused(tmp_path, monkeypatch, image):
    def not_variable(*_args):
        raise SiteOutputError("followup_provenance_unverified")

    record = make_pipeline_njr(job_id="edit", stage_chain=(make_stage_config("img2img"),))
    monkeypatch.setattr(site_phone_followup, "verified_history_source", not_variable)
    monkeypatch.setattr(
        site_phone_followup, "verified_recipe_source", lambda *_args: (record, "fp")
    )
    compiler = AppActionCompiler(Host(), repository=Mock(), output_root=tmp_path)

    with pytest.raises(ActionRefused) as refused:
        compiler.compile("more_like_this", image, _digest(image), (1,))
    assert refused.value.detail == "recipe_not_variable"


def _embedded(path: Path, job_id: str, njr_sha: str) -> bytes:
    from src.utils.image_metadata import build_contract_kv, write_image_metadata

    Image.new("RGB", (64, 64), "#123456").save(path)
    payload = {"generation": {"model": "sdxl"}, "stage_manifest": {"stage": "adetailer"}}
    assert write_image_metadata(
        path,
        build_contract_kv(
            payload, job_id=job_id, run_id="run", stage="adetailer", njr_sha256=njr_sha
        ),
    )
    return path.read_bytes()


def test_the_recipe_source_is_the_completed_job_that_recorded_this_file(tmp_path):
    from src.queue.job_model import JobStatus
    from src.utils.njr_identity import snapshot_fingerprint

    record = _multi_stage("job-7")
    snapshot = {"normalized_job": record.to_dict()}
    fingerprint = snapshot_fingerprint(snapshot)
    image = tmp_path / "final.png"
    raw = _embedded(image, "job-7", fingerprint)
    entry = SimpleNamespace(
        job_id="job-7",
        status=JobStatus.COMPLETED,
        snapshot=snapshot,
        result={"artifact": {"primary_path": str(image), "output_paths": [str(image)]}},
    )
    repository = SimpleNamespace(get_job=lambda job_id: entry if job_id == "job-7" else None)

    found, found_fingerprint = site_phone_followup.verified_recipe_source(repository, image, raw)
    assert (found.job_id, found.stage_chain_labels, found_fingerprint) == (
        "job-7",
        ["txt2img", "adetailer"],
        fingerprint,
    )

    other = tmp_path / "other.png"
    for broken in (
        SimpleNamespace(**{**vars(entry), "status": JobStatus.FAILED}),
        SimpleNamespace(**{**vars(entry), "result": {"artifact": {"primary_path": str(other)}}}),
        SimpleNamespace(**{**vars(entry), "snapshot": {}}),
    ):
        with pytest.raises(SiteOutputError, match="followup_provenance_unverified"):
            site_phone_followup.verified_recipe_source(
                SimpleNamespace(get_job=lambda _id, b=broken: b), image, raw
            )
    forged = _embedded(tmp_path / "forged.png", "job-7", "0" * 64)
    with pytest.raises(SiteOutputError, match="followup_provenance_unverified"):
        site_phone_followup.verified_recipe_source(repository, tmp_path / "forged.png", forged)


# -- the preview host against the real Review compilers ----------------------------------------------------------


def _app(baseline):
    return SimpleNamespace(
        _is_shutting_down=False,
        _ui_dispatch=lambda callback: callback(),
        _build_reprocess_config=lambda stages: {
            "model": "sdxl",
            "backend_options": {"image": {"backend_id": "forge_webui"}},
            "img2img": {"denoising_strength": 0.3, "steps": 20, "cfg_scale": 6.5, "seed": 42},
        },
        _extract_reprocess_baseline_from_image=lambda path: dict(baseline),
        app_state=SimpleNamespace(
            resources={"models": [SimpleNamespace(name=JUGG), PONY, "", PONY]}
        ),
    )


def test_the_host_lists_the_backends_checkpoints_once_each(tmp_path):
    from src.app.site_phone_preview_host import PhonePreviewHost

    host = PhonePreviewHost(_app({}), Mock(), tmp_path / "records.jsonl")

    assert host.gateway_models() == (JUGG, PONY)


def test_the_host_compiles_another_model_and_a_prompt_tweak_as_review_img2img(tmp_path):
    from src.app.site_phone_preview_host import PhonePreviewHost

    image = tmp_path / "source.png"
    Image.new("RGB", (64, 64), "#223344").save(image)
    digest = _digest(image)
    baseline = {"model": "sdxl", "prompt": "a lighthouse", "vae": "sdxl_vae.safetensors"}
    host = PhonePreviewHost(_app(baseline), Mock(), tmp_path / "records.jsonl")

    swapped = host.compile_gateway_img2img(image, digest, model="ponyXL.safetensors")
    [job] = swapped.records
    assert job.base_model == "ponyXL.safetensors"
    assert job.stage_chain_labels == ["img2img"]
    assert job.source.parent_artifact_id == f"sha256:{digest}"
    assert job.config.get("vae") in (
        None,
        "",
    )  # the recorded VAE belonged to the recorded checkpoint
    swapped.require_current()

    tweaked = host.compile_gateway_img2img(image, digest, prompt_add="smiling")
    [job] = tweaked.records
    assert job.base_model == "sdxl"
    assert job.positive_prompt.startswith("a lighthouse") and "smiling" in job.positive_prompt


def test_the_host_compiles_an_aspect_ratio_as_reviews_outpaint(tmp_path, monkeypatch):
    from src.app.site_phone_preview_host import PhonePreviewHost
    from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
    from src.image_backends import masked_inpaint as capability
    from src.pipeline import image_edit_inputs as inputs

    monkeypatch.setattr(
        inputs, "default_snapshot_root", lambda: tmp_path / "state" / "image_edit_inputs"
    )
    monkeypatch.setattr(
        capability,
        "RegistryFamilyLookup",
        lambda: lambda name: CompatibilityProfile(
            CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ()
        )
        if name == "sdxl"
        else None,
    )
    image = tmp_path / "square.png"
    Image.new("RGB", (128, 128), "#556677").save(image)
    digest = _digest(image)
    host = PhonePreviewHost(
        _app({"model": "sdxl", "prompt": "a meadow", "job_id": "parent"}),
        Mock(),
        tmp_path / "records.jsonl",
    )

    draft = host.compile_gateway_outpaint(image, digest, ratio=(2, 3))

    [job] = draft.records
    stage = job.config["img2img"]
    assert (stage["width"], stage["height"]) == (128, 192)
    assert job.source.parent_artifact_id == f"sha256:{digest}"
    draft.require_current()
    with pytest.raises(SiteOutputError, match="no_change"):
        host.compile_gateway_outpaint(image, digest, ratio=(1, 1))
    wide = tmp_path / "wide.png"
    Image.new("RGB", (4096, 1024), "#556677").save(wide)
    with pytest.raises(SiteOutputError, match="size_unsupported"):
        host.compile_gateway_outpaint(wide, _digest(wide), ratio=(4, 5))
    unprompted = PhonePreviewHost(_app({"model": "sdxl"}), Mock(), tmp_path / "records.jsonl")
    with pytest.raises(SiteOutputError, match="prompt_required"):
        unprompted.compile_gateway_outpaint(image, digest, ratio=(2, 3))


# -- Make Video against the real catalog --------------------------------------------------------------------------


def test_make_video_compiles_the_recommended_approved_workflow_from_the_image(tmp_path):
    from src.app.site_phone_video import gateway_make_video
    from src.video.workflow_frame_count import frame_count_policy

    root = (tmp_path / "output").resolve()
    root.mkdir()
    image = root / "portrait.png"
    Image.new("RGB", (832, 1216), "#557733").save(image)
    digest = _digest(image)

    spec, draft = gateway_make_video(root, image, digest, "a lighthouse at dusk", 1234)

    assert spec.backend_defaults.get("make_video_default") and not spec.is_experimental
    [job] = draft.records
    assert job.workload_kind is WorkloadKind.VIDEO
    assert job.positive_prompt == "a lighthouse at dusk"
    frames = frame_count_policy(spec)
    assert frames is not None
    draft.require_current()
    with pytest.raises(SiteOutputError, match="source_changed"):
        gateway_make_video(root, image, "0" * 64, "a lighthouse at dusk", 1234)
