"""P4-2A golden NJRs for the reprocess family and every video route that compiles through ``ReprocessJobBuilder``.

Routes: Reprocess/Review img2img, frozen masked edit, native SVD, Comfy Video Workflow, Movie Clips, a Comfy sequence
plan, and a sequence resume and replay (assessment sites S4 and V4).  Ids are injected (``fixed_reprocess_ids`` or
``id_fn``); the only masked value is a ledger digest, which depends on a file this test writes, and the test asserts
that it equals the file's own digest.  X10 (every video stage is written as ``video_workflow``) is frozen as observed.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
from src.controller import masked_edit_service as edits
from src.controller.svd_controller import SVDController
from src.controller.video_workflow_controller import VideoWorkflowController
from src.image_backends import masked_inpaint as capability
from src.pipeline import image_edit_inputs as inputs
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.reprocess_builder import ReprocessJobBuilder, ReprocessSourceItem
from src.video.movie_assembly_compiler import (
    AssemblyIntentClip,
    MovieAssemblyIntent,
    VideoFacts,
    build_movie_assembly_njr,
    freeze_movie_assembly,
)
from src.video.sequence_ledger import LEDGER_FILE_NAME, sha256_of
from src.video.sequence_resume import build_replay_njr, build_resume_njr, plan_from_njr
from src.video.svd_config import SVDConfig
from tests.golden.test_njr_golden_p4_2 import assert_golden

WORKFLOW = "wan22_ti2v_5b_i2v_v1"


class CapturingJobService:
    """Records what a controller submits; nothing is queued or run."""

    def __init__(self) -> None:
        self.submitted: list[NormalizedJobRecord] = []
        self.queue = SimpleNamespace(get_job=lambda _job_id: None)

    def submit_njrs(self, njrs: Any, _policy: Any) -> list[str]:
        self.submitted.extend(njrs)
        return [f"queued-{len(self.submitted)}"]


def video_controller(tmp_path: Path) -> tuple[VideoWorkflowController, CapturingJobService]:
    service = CapturingJobService()
    app = SimpleNamespace(job_service=service, output_dir=str(tmp_path / "output"))
    return VideoWorkflowController(app_controller=app), service


def video_form(**changes: Any) -> dict[str, Any]:
    return {
        "workflow_id": WORKFLOW,
        "workflow_version": "1.3.0",
        "prompt": "the person waves",
        "frame_count": 17,
        "seed": 1234,
        **changes,
    }


def sequence_intent(count: int = 3) -> dict[str, Any]:
    return {
        "sequence_id": "golden-sequence",
        "segments": [{"frame_count": 17, "seed": 100 + index} for index in range(count)],
        "assembly": {"clip_name": "walk", "quality": "draft"},
    }


# ---------------------------------------------------------------------------------------------- Reprocess / Review


def test_reprocess_img2img_grouped(
    tmp_path: Path, copy_asset: Callable[..., Path], fixed_reprocess_ids: Callable[[], str]
) -> None:
    first = copy_asset("blue_64.png", "in/first.png")
    second = copy_asset("blue_64.png", "in/second.png")
    plan = ReprocessJobBuilder().build_grouped_reprocess_jobs(
        items=[
            ReprocessSourceItem(
                input_image_path=str(path),
                prompt="a clean portrait",
                negative_prompt="blurry",
                model="sdxl.safetensors",
                config={
                    "img2img": {"denoising_strength": 0.4, "steps": 18, "cfg_scale": 6.0},
                    "seed": 77,
                },
            )
            for path in (first, second)
        ],
        stages=["img2img"],
        batch_size=2,
        pack_name="Review Golden",
        source="reprocess",
        output_dir=str(tmp_path / "output"),
    )
    assert len(plan.jobs) == 1 and len(plan.jobs[0].input_image_paths) == 2
    assert_golden("reprocess_img2img", [job.to_dict() for job in plan.jobs], tmp_path)


def test_reprocess_frozen_mask_edit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    copy_asset: Callable[..., Path],
    fixed_reprocess_ids: Callable[[], str],
) -> None:
    monkeypatch.setattr(
        inputs, "default_snapshot_root", lambda: tmp_path / "state" / "image_edit_inputs"
    )

    def lookup(name: str) -> CompatibilityProfile | None:
        if name == "sdxl":
            return CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ())
        return None

    monkeypatch.setattr(capability, "RegistryFamilyLookup", lambda: lookup)
    source = copy_asset("blue_64.png", "original.png")
    mask = (Path(__file__).resolve().parent / "assets" / "mask_64.png").read_bytes()
    preview = edits.prepare_mask_edit(
        source_path=str(source),
        source_sha256=inputs.read_source(source).sha256,
        mask_data=mask,
        settings=edits.MaskEditSettings("replace the blue region with flowers", 0.55, 8, 24),
        fallback_config={
            "model": "sdxl",
            "backend_options": {"image": {"backend_id": "forge_webui"}},
            "img2img": {
                "steps": 23,
                "sampler_name": "Euler",
                "scheduler": "Karras",
                "cfg_scale": 6.5,
                "seed": 42,
            },
        },
        baseline={"model": "sdxl", "job_id": "parent-job"},
    )
    assert preview.job.source.kind.value == "image_edit"
    assert_golden("reprocess_frozen_mask_edit", preview.job.to_dict(), tmp_path)


# ------------------------------------------------------------------------------------------------- native SVD


def test_native_svd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    copy_asset: Callable[..., Path],
    fixed_reprocess_ids: Callable[[], str],
) -> None:
    monkeypatch.setattr(
        "src.controller.svd_controller.get_svd_preflight",
        lambda _config, **_kwargs: SimpleNamespace(available=True, blocking_reasons=()),
    )
    # Default post-processing model paths hang off the home directory; pin it so the snapshot is portable.
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path / "home"))
    source = copy_asset("portrait_480x832.png", "in/portrait.png")
    service = CapturingJobService()
    controller = SVDController(
        app_controller=SimpleNamespace(output_dir=str(tmp_path / "output"), job_service=service),
        svd_service=SimpleNamespace(),
    )
    controller.submit_svd_job(
        source_image_path=source,
        config=SVDConfig.from_dict({"inference": {"num_frames": 25, "seed": 2024}}),
    )
    assert len(service.submitted) == 1
    assert_golden("svd_native", service.submitted[0].to_dict(), tmp_path)


# --------------------------------------------------------------------------------------- Comfy Video Workflow


def test_comfy_video_workflow(
    tmp_path: Path, copy_asset: Callable[..., Path], fixed_reprocess_ids: Callable[[], str]
) -> None:
    controller, service = video_controller(tmp_path)
    source = copy_asset("portrait_480x832.png", "in/portrait.png")
    controller.submit_video_workflow_job(source_image_path=source, form_data=video_form())
    assert len(service.submitted) == 1
    assert_golden("video_workflow", service.submitted[0].to_dict(), tmp_path)


# -------------------------------------------------------------------------------------------------- Movie Clips


def test_movie_clips(tmp_path: Path, copy_asset: Callable[..., Path]) -> None:
    clips = [
        copy_asset("still_red_40x30.png", "src/b.png"),
        copy_asset("still_blue_40x30.png", "src/a.png"),
    ]
    spec = freeze_movie_assembly(
        MovieAssemblyIntent(
            clips=tuple(AssemblyIntentClip(str(path), 0.5) for path in clips),
            fps=8,
            transition_seconds=0.125,
        ),
        video_probe=lambda _path: VideoFacts(8, 8, 1.0, None),
        audio_probe=lambda _path: None,
    )
    record = build_movie_assembly_njr(
        spec,
        output_dir=tmp_path / "output",
        builder=ReprocessJobBuilder(id_fn=lambda: "movie-1"),
    )
    assert_golden("movie_clips", record.to_dict(), tmp_path)


# --------------------------------------------------------------------------------- sequence plan, resume, replay


def _sequence_parent(
    tmp_path: Path, copy_asset: Callable[..., Path]
) -> tuple[NormalizedJobRecord, Path]:
    controller, _service = video_controller(tmp_path)
    source = copy_asset("portrait_480x832.png", "in/portrait.png")
    built = controller.build_sequence_job(
        source_image_path=str(source),
        form_data=video_form(),
        sequence_intent=sequence_intent(),
    )
    return built.njr, source


def test_sequence_plan_job(
    tmp_path: Path, copy_asset: Callable[..., Path], fixed_reprocess_ids: Callable[[], str]
) -> None:
    parent, _source = _sequence_parent(tmp_path, copy_asset)
    assert len(plan_from_njr(parent, "video_workflow").segments) == 3
    assert_golden("sequence_plan_job", mask_environment_digests(parent.to_dict()), tmp_path)


def _failed_ledger(parent: NormalizedJobRecord, source: Path, run_dir: Path) -> Path:
    from src.pipeline.video_sequence_executor import VideoSequenceExecutor
    from tests.video.test_pr_vid_seq_330_executor import Segments, _fake_assemble

    plan = plan_from_njr(parent, "video_workflow")
    with pytest.raises(RuntimeError):
        VideoSequenceExecutor(
            plan=plan,
            job_id=parent.job_id,
            run_dir=run_dir,
            run_segment=Segments(run_dir, fail_on=2),
            assemble=_fake_assemble,
        ).execute(source_image_path=str(source))
    return run_dir / LEDGER_FILE_NAME


_ENV_DIGEST_KEYS = (
    "digest",
    "plan_digest",
    "snapshot_sha256",
    "plan_sha256",
    "parent_ledger_sha256",
)


def mask_environment_digests(node: Any) -> Any:
    """Mask digests that hash a temp path or a file this test wrote, after checking each is a SHA-256.

    The sequence plan digest covers the (temp) source path and the ledger digest covers a ledger holding temp paths, so
    both change with the pytest temp directory.  Their inputs are pinned by the rest of the snapshot.
    """

    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key in _ENV_DIGEST_KEYS and isinstance(value, str):
                assert len(value) == 64 and int(value, 16) >= 0
                out[key] = "<env_digest>"
            else:
                out[key] = mask_environment_digests(value)
        return out
    if isinstance(node, list):
        return [mask_environment_digests(value) for value in node]
    return node


def test_sequence_resume_and_replay(
    tmp_path: Path, copy_asset: Callable[..., Path], fixed_reprocess_ids: Callable[[], str]
) -> None:
    parent, source = _sequence_parent(tmp_path, copy_asset)
    ledger = _failed_ledger(parent, source, tmp_path / "parent-run")
    resume = build_resume_njr(
        parent, stage_name="video_workflow", ledger_path=ledger, id_fn=lambda: "resume-1"
    )
    replay = build_replay_njr(
        parent, stage_name="video_workflow", ledger_path=ledger, id_fn=lambda: "replay-1"
    )
    block = dict(resume.stage_chain[0].extra)["sequence_resume"]
    assert block["parent_ledger_sha256"] == sha256_of(ledger)
    snapshot = copy.deepcopy({"resume": resume.to_dict(), "replay": replay.to_dict()})
    assert_golden("sequence_resume_and_replay", mask_environment_digests(snapshot), tmp_path)
