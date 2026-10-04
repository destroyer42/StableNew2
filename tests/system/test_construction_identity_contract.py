"""Required cross-boundary contract: immutable job identity survives every NJR construction boundary.

PR-DEVEX-CI-110 (born of the PR-IMG-116 reprocess regression). Not an image-backend feature test: it protects the
architectural rule that persisted backend/model-profile identity is never silently stripped, substituted or accepted by
an incompatible backend when work passes through builders, adapters and serialization. It runs in the always-required
gate, builds nothing heavier than the production builders, and performs no HTTP, GPU or GUI work.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from src.image_backends.forge_klein_profile import (
    KleinProfileError,
    latest_klein_profile,
    resolve_model_profile,
)
from src.image_backends.image_backend_registry import build_default_image_backend_registry
from src.image_backends.image_backend_types import resolve_image_backend_id
from src.pipeline.cli_njr_builder import build_cli_njr
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.reprocess_builder import ReprocessJobBuilder, ReprocessSourceItem

PROFILE = latest_klein_profile()
PROFILED_MODEL = PROFILE.transformer.filename
PLAIN_MODEL = "sdxl.safetensors"


@pytest.fixture(autouse=True)
def _configured_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.image_backends.image_backend_types.configured_image_backend_id", lambda: "forge_webui")


@pytest.fixture
def source_image(tmp_path: Path) -> Path:
    path = tmp_path / "source.png"
    Image.new("RGB", (768, 1024), (10, 20, 30)).save(path)
    return path


def _via_job_builder(model: str, _src: Path) -> NormalizedJobRecord:
    config = {"prompt": "p", "model": model, "txt2img": {"model": model}, "seed": 1, "width": 768, "height": 1024}
    return JobBuilderV2(id_fn=lambda: "contract-job").build_jobs(base_config=config)[0]


def _via_cli(model: str, _src: Path) -> NormalizedJobRecord:
    return build_cli_njr(prompt="p", config={"txt2img": {"model": model, "width": 768, "height": 1024}}, batch_size=1, run_name="contract-cli")


def _via_reprocess_job(model: str, src: Path) -> NormalizedJobRecord:
    return ReprocessJobBuilder().build_reprocess_job([src], ["adetailer"], model=model, output_dir=str(src.parent / "out"))


def _via_review_restored_artifact(model: str, src: Path) -> NormalizedJobRecord:
    """What Review does: the model comes back from artifact metadata; nothing marks the job as special."""

    item = ReprocessSourceItem(input_image_path=str(src), prompt="p", model=model)
    plan = ReprocessJobBuilder().build_grouped_reprocess_jobs(
        items=[item], stages=["upscale"], fallback_config={}, batch_size=1, output_dir=str(src.parent / "out"))
    return plan.jobs[0]


BUILDERS = [_via_job_builder, _via_cli, _via_reprocess_job, _via_review_restored_artifact]


@pytest.mark.parametrize("build", BUILDERS)
def test_every_construction_path_persists_an_explicit_backend_identity(build, source_image: Path) -> None:
    njr = build(PLAIN_MODEL, source_image)
    assert njr.backend_options["image"]["backend_id"] == "forge_webui"
    assert resolve_image_backend_id(njr.backend_options) == "forge_webui"


@pytest.mark.parametrize("build", BUILDERS)
def test_a_profiled_model_never_loses_its_versioned_profile_through_construction(build, source_image: Path) -> None:
    njr = build(PROFILED_MODEL, source_image)
    assert njr.backend_options["image"]["model_profile"] == PROFILE.reference()
    assert resolve_model_profile(njr.backend_options) is PROFILE


@pytest.mark.parametrize("build", BUILDERS)
def test_an_unprofiled_model_gets_no_profile_from_any_builder(build, source_image: Path) -> None:
    assert "model_profile" not in build(PLAIN_MODEL, source_image).backend_options["image"]


@pytest.mark.parametrize("build", BUILDERS)
def test_backend_and_profile_identity_survive_njr_serialization_and_replay_reconstruction(build, source_image: Path) -> None:
    njr = build(PROFILED_MODEL, source_image)
    restored = NormalizedJobRecord.from_dict(njr.to_dict())
    assert restored.backend_options == njr.backend_options


def test_a_profile_is_accepted_only_by_its_own_backend_and_never_reinterpreted(source_image: Path) -> None:
    njr = _via_review_restored_artifact(PROFILED_MODEL, source_image)
    registry = build_default_image_backend_registry()
    for backend_id in registry.list_backend_ids():
        backend = registry.get(backend_id)
        validate = backend.validate_njr_intent
        if backend_id == PROFILE.backend_id:
            with pytest.raises(KleinProfileError):  # its own backend still enforces the envelope (unsupported chain)
                validate(njr, ["upscale"])
        else:
            with pytest.raises(KleinProfileError, match="requires the"):  # a foreign backend never accepts it
                validate(njr, ["upscale"])
    with pytest.raises(KleinProfileError):
        resolve_model_profile({"image": {"model_profile": {"id": PROFILE.profile_id, "version": PROFILE.version + 1}}})
    with pytest.raises(KeyError):  # no fallback to another backend for an unknown identity
        registry.get("not_a_backend")
