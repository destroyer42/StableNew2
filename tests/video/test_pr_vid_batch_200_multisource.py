"""PR-VID-BATCH-200: multi-source Video Workflow batch (assess -> freeze -> all-or-none admit).

CPU-only and deterministic: temp files, Pillow synthetic images, the real builder / JobService /
SQLite repository / sequential runner, fake backends.  No Comfy, WebUI, GPU or network.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from src.controller.job_service import JobService
from src.controller.video_workflow_controller import VideoWorkflowController
from src.queue.backend_dependency import BackendDependency, classify_job
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from src.video.video_workflow_batch import (
    BATCH_KIND,
    BATCH_SCHEMA,
    MAX_BATCH_SOURCES,
    BatchRefused,
    VideoWorkflowBatchService,
    scan_folder,
    select_sources,
)
from src.video.video_workflow_njr_builder import VideoWorkflowNjrBuilder
from src.video.workflow_catalog_wan_animate2 import (
    WAN_ANIMATE2_CONTROLS_VERSION,
    WAN_ANIMATE2_DRIVE_ID,
)

TI2V_ID = "wan22_ti2v_5b_i2v_v1"


class _JobService:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def submit_njrs(self, njrs, policy):
        self.calls.append(list(njrs))
        return [njr.job_id for njr in njrs]


def _stack(tmp_path: Path, job_service: Any = None):
    service = job_service or _JobService()
    app = SimpleNamespace(
        job_service=service,
        output_dir=str(tmp_path / "output"),
        sync_queue_state_after_direct_submission=lambda: None,
    )
    return VideoWorkflowController(app_controller=app), service


def _images(tmp_path: Path, count: int, *, folder: str = "src") -> list[Path]:
    root = tmp_path / folder
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    for index in range(count):
        path = root / f"img_{index:02d}.png"
        Image.new("RGB", (48 + index, 80), ((index * 9) % 256, 40, 90)).save(path)
        paths.append(path)
    return paths


def _form(**overrides: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "workflow_id": TI2V_ID,
        "workflow_version": "1.1.0",
        "prompt": "slow cinematic turn",
        "negative_prompt": "",
        "experimental_opt_in": True,
        "seed": "",
        "frame_count": 33,
    }
    form.update(overrides)
    return form


def _preview(tmp_path: Path, count: int = 3, **form_overrides: Any):
    controller, service = _stack(tmp_path)
    paths = _images(tmp_path, count)
    selection = controller.select_batch_sources([str(p) for p in paths])
    plan = controller.preview_batch(sources=selection.sources, form_data=_form(**form_overrides))
    return controller, service, paths, plan


def _sha(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _same_size_replace(path: Path) -> None:
    """Change the bytes but keep the size and the mtime, so only a content hash can notice."""

    stat = path.stat()
    path.write_bytes(bytes(reversed(path.read_bytes())))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert path.stat().st_size == stat.st_size and path.stat().st_mtime_ns == stat.st_mtime_ns


# ------------------------------------------------------------------ baseline contract


def test_baseline_single_source_submission_is_one_job_per_call(tmp_path):
    """Pre-existing behavior this PR must preserve: the ordinary path stays one source/one job."""

    controller, service = _stack(tmp_path)
    form = _form()
    job_id = controller.submit_video_workflow_job(
        source_image_path=_images(tmp_path, 1)[0], form_data=form
    )
    assert len(service.calls) == 1 and len(service.calls[0]) == 1
    assert service.calls[0][0].job_id == job_id
    # Single-source provenance is unchanged: no batch descriptor and no source-identity block.
    metadata = dict(service.calls[0][0].provenance.metadata)
    assert "batch" not in metadata
    assert "source_identity" not in dict(metadata["video_workflow"])


# ------------------------------------------------------------------ source-count boundaries


@pytest.mark.parametrize("count", [1, 10, MAX_BATCH_SOURCES])
def test_one_to_twenty_five_accepted_sources_build_independent_jobs(tmp_path, count):
    controller, service, paths, plan = _preview(tmp_path, count)

    assert plan.eligible, plan.assessment.problems
    assert len(plan.njrs) == count
    assert len({njr.job_id for njr in plan.njrs}) == count
    assert plan.job_ids == tuple(njr.job_id for njr in plan.njrs)
    assert [job.path for job in plan.jobs] == [str(p) for p in paths]
    assert service.calls == []  # a preview never queues

    result = controller.submit_batch(plan)
    assert len(service.calls) == 1  # ONE submit_njrs call for the whole batch
    assert list(result.job_ids) == [njr.job_id for njr in service.calls[0]]
    assert result.batch_id == plan.batch_id and len(result.job_ids) == count


def test_twenty_six_sources_are_refused_not_truncated(tmp_path):
    controller, service = _stack(tmp_path)
    paths = _images(tmp_path, MAX_BATCH_SOURCES + 1)
    selection = controller.select_batch_sources([str(p) for p in paths])
    assert len(selection.sources) == 26  # the selection itself is never silently cut

    plan = controller.preview_batch(sources=selection.sources, form_data=_form())

    assert not plan.eligible and plan.njrs == ()
    assert len(plan.assessment.rows) == 26
    assert any("26 sources" in text and "1 to 25" in text for text in plan.assessment.batch_errors)
    assert not (tmp_path / "output" / "prepared_video_sources").exists()  # nothing was prepared
    with pytest.raises(BatchRefused, match="not eligible"):
        controller.submit_batch(plan)
    assert service.calls == []


def test_empty_selection_is_refused(tmp_path):
    controller, service = _stack(tmp_path)
    plan = controller.preview_batch(sources=(), form_data=_form())
    assert not plan.eligible
    assert any("1 to 25" in text for text in plan.assessment.batch_errors)
    assert service.calls == []


# ------------------------------------------------------------------ selection semantics


def test_selected_files_keep_order_and_duplicates_are_counted(tmp_path):
    paths = _images(tmp_path, 3)
    spelled = [
        str(paths[2]),
        str(paths[0]),
        str(paths[2].parent / ".." / paths[2].parent.name / paths[2].name),  # same file again
        str(paths[1]),
        str(paths[0]),
        "",  # blank entries are ignored, not counted as sources
    ]
    selection = select_sources(spelled)
    assert [Path(s.path).name for s in selection.sources] == [
        "img_02.png",
        "img_00.png",
        "img_01.png",
    ]
    assert selection.duplicates_omitted == 2


def test_folder_selection_is_deterministic_and_states_its_traversal(tmp_path):
    root = tmp_path / "folder"
    (root / "sub").mkdir(parents=True)
    for name in ("b.png", "A.png", "c.jpg", "notes.txt"):
        target = root / name
        if name.endswith("txt"):
            target.write_text("not an image")
        else:
            Image.new("RGB", (16, 16), "red").save(target)
    Image.new("RGB", (16, 16), "blue").save(root / "sub" / "a.png")

    recursive = scan_folder(root)
    names = [str(Path(s.path).relative_to(root)) for s in recursive.sources]
    assert names == ["A.png", "b.png", "c.jpg", str(Path("sub") / "a.png")]
    assert "including subfolders" in recursive.note
    assert [s.path for s in scan_folder(root).sources] == [s.path for s in recursive.sources]

    flat = scan_folder(root, recursive=False)
    assert [Path(s.path).name for s in flat.sources] == ["A.png", "b.png", "c.jpg"]
    assert "top level only" in flat.note
    with pytest.raises(BatchRefused, match="does not exist"):
        scan_folder(root / "missing")


# ------------------------------------------------------------------ eligibility and blocked sources


def test_assessment_reports_workflow_controls_and_destination_without_writing(tmp_path):
    controller, _service = _stack(tmp_path)
    paths = _images(tmp_path, 2)
    selection = controller.select_batch_sources([str(p) for p in paths])
    service = VideoWorkflowBatchService(controller._njr_builder)

    assessment = service.assess(_form(seed="99"), selection.sources)

    assert assessment.eligible
    assert (assessment.workflow_id, assessment.workflow_version) == (TI2V_ID, "1.1.0")
    assert assessment.backend_id == "comfy" and assessment.governance_state == "experimental"
    assert assessment.experimental and assessment.opt_in_granted
    assert {c.name for c in assessment.controls} >= {"source_image", "prompt_text"}
    assert all(c.accepted for c in assessment.controls)
    assert assessment.frame_count == 33 and assessment.approximate_seconds == 1.4
    assert (assessment.seed_policy, assessment.explicit_seed) == ("explicit", 99)
    assert assessment.free_bytes is not None
    row = assessment.rows[0]
    assert (row.width, row.height, row.orientation) == (48, 80, "portrait")
    assert row.target == (480, 832) and row.preparation == "create"
    assert any("not a qualification" in note for note in assessment.notes)
    assert any("prepares source images" in note for note in assessment.notes)
    # Read-only: nothing was published.
    assert not (tmp_path / "output").exists()


def test_blank_seed_policy_and_unaccepted_control_are_reported(tmp_path):
    controller, _ = _stack(tmp_path)
    selection = controller.select_batch_sources([str(p) for p in _images(tmp_path, 1)])
    service = VideoWorkflowBatchService(controller._njr_builder)
    assessment = service.assess(
        _form(end_anchor_path=str(_images(tmp_path, 1, folder="anchor")[0])), selection.sources
    )
    assert assessment.seed_policy == "per_source_random"
    assert not assessment.eligible
    assert "does not accept the requested end anchor" in assessment.form_error
    assert [c for c in assessment.controls if not c.accepted][0].name == "end_anchor"


def test_unchecked_experimental_opt_in_blocks_the_whole_batch(tmp_path):
    _controller, service, _paths, plan = _preview(tmp_path, 2, experimental_opt_in=False)
    assert not plan.eligible and "experimental workflow" in plan.assessment.form_error
    assert plan.njrs == () and service.calls == []


def test_one_bad_source_among_twenty_five_blocks_all_and_is_named(tmp_path):
    controller, service = _stack(tmp_path)
    paths = _images(tmp_path, MAX_BATCH_SOURCES)
    paths[12].write_bytes(b"this is not a png")  # corrupt, still named .png
    selection = controller.select_batch_sources([str(p) for p in paths])

    plan = controller.preview_batch(sources=selection.sources, form_data=_form())

    assert not plan.eligible and plan.njrs == () and plan.jobs == ()
    blocked = plan.assessment.blocked_rows
    assert [row.index for row in blocked] == [12]
    assert "Unreadable image" in blocked[0].reasons[0]
    assert len(plan.assessment.rows) == 25  # every source is still shown
    assert not (tmp_path / "output" / "prepared_video_sources").exists()
    with pytest.raises(BatchRefused):
        controller.submit_batch(plan)
    assert service.calls == []  # never "the other 24"


def test_multiple_bad_sources_each_get_their_own_reason(tmp_path):
    controller, service = _stack(tmp_path)
    paths = _images(tmp_path, 5)
    paths[0].unlink()  # missing
    paths[2].write_bytes(b"garbage")  # undecodable
    renamed = paths[3].with_suffix(".txt")  # unsupported type
    paths[3].rename(renamed)
    selection = controller.select_batch_sources(
        [str(paths[0]), str(paths[1]), str(paths[2]), str(renamed), str(paths[4])]
    )
    plan = controller.preview_batch(sources=selection.sources, form_data=_form())

    reasons = {row.index: row.reasons[0] for row in plan.assessment.blocked_rows}
    assert set(reasons) == {0, 2, 3}
    assert "does not exist" in reasons[0]
    assert "Unreadable image" in reasons[2]
    assert "Unsupported source file type" in reasons[3]
    assert service.calls == []


def test_excluding_blocked_sources_requires_a_fresh_preview_and_admits_only_that_list(tmp_path):
    controller, service = _stack(tmp_path)
    paths = _images(tmp_path, 4)
    paths[1].write_bytes(b"garbage")
    selection = controller.select_batch_sources([str(p) for p in paths])
    first = controller.preview_batch(sources=selection.sources, form_data=_form())
    assert not first.eligible

    kept = [s for s in selection.sources if s.path != str(paths[1])]
    second = controller.preview_batch(sources=kept, form_data=_form())
    assert second.eligible and second.batch_id != first.batch_id
    result = controller.submit_batch(second)
    assert len(service.calls) == 1 and len(result.job_ids) == 3
    assert list(result.sources) == [str(paths[0]), str(paths[2]), str(paths[3])]


def test_destination_that_cannot_hold_preparation_blocks(tmp_path):
    controller, _ = _stack(tmp_path)
    selection = controller.select_batch_sources([str(p) for p in _images(tmp_path, 2)])
    service = VideoWorkflowBatchService(controller._njr_builder, free_bytes=lambda _p: 1024)
    assessment = service.assess(_form(), selection.sources)
    assert not assessment.eligible
    assert "Not enough free space" in assessment.destination_error

    low = VideoWorkflowBatchService(
        controller._njr_builder, free_bytes=lambda _p: 2 * 1024**3
    ).assess(_form(), selection.sources)
    assert low.eligible  # enough to prepare, but warned about sustained generation
    assert any("may run out of space" in warning for warning in low.warnings)


def test_unwritable_destination_file_blocks(tmp_path):
    blocker = tmp_path / "output"
    blocker.write_text("a file where the output folder should be")
    controller, _ = _stack(tmp_path)
    selection = controller.select_batch_sources([str(p) for p in _images(tmp_path, 1)])
    plan = controller.preview_batch(sources=selection.sources, form_data=_form())
    assert not plan.eligible and "not a folder" in plan.assessment.destination_error


def test_identical_content_is_warned_not_silently_merged(tmp_path):
    controller, _ = _stack(tmp_path)
    paths = _images(tmp_path, 2)
    twin = paths[0].with_name("twin.png")
    twin.write_bytes(paths[0].read_bytes())
    selection = controller.select_batch_sources([str(paths[0]), str(paths[1]), str(twin)])
    plan = controller.preview_batch(sources=selection.sources, form_data=_form())
    assert plan.eligible and len(plan.njrs) == 3  # different paths remain different jobs
    assert any("identical image content" in w for w in plan.assessment.warnings)
    assert len({njr.job_id for njr in plan.njrs}) == 3


# ------------------------------------------------------------------ freezing and provenance


def test_every_job_freezes_its_own_source_hashes_batch_lineage_and_workflow_identity(tmp_path):
    _controller, _service, paths, plan = _preview(tmp_path, 4, seed="123")

    assert plan.eligible
    prepared = set()
    for position, (njr, path) in enumerate(zip(plan.njrs, paths, strict=True)):
        metadata = dict(njr.provenance.metadata)
        batch = dict(metadata["batch"])
        assert batch == {
            "schema": BATCH_SCHEMA,
            "batch_id": plan.batch_id,
            "batch_kind": BATCH_KIND,
            "source_index": position,  # documented 0-based convention
            "source_count": 4,
        }
        identity = dict(dict(metadata["video_workflow"])["source_identity"])
        assert identity["original_path"] == str(path)
        assert identity["original_sha256"] == _sha(path)
        assert identity["prepared_sha256"] == _sha(identity["prepared_path"])
        assert identity["preparation_policy"] == "cover_resize_center_crop"
        assert identity["original_sha256"] != identity["prepared_sha256"]
        assert njr.input_image_paths == (identity["prepared_path"],)
        prepared.add(identity["prepared_path"])

        block = njr.config["video_workflow"]
        assert (block["workflow_id"], block["workflow_version"]) == (TI2V_ID, "1.1.0")
        assert block["backend_id"] == "comfy"
        assert block["frame_count"] == 33 and block["fps"] == 24
        assert block["prompt"] == "slow cinematic turn"
        assert block["seed"] == 123  # explicit seed shared by every job
        assert block["video_execution"]["experimental_opt_in"] is True
        assert "parent_job_id" not in metadata  # no invented parent
        assert njr.source.parent_job_id is None
    assert len(prepared) == 4  # distinct prepared sources
    assert len({njr.job_id for njr in plan.njrs}) == 4


def test_blank_seed_freezes_a_concrete_independent_seed_per_source(tmp_path):
    controller, service, _paths, plan = _preview(tmp_path, 8, seed="")
    seeds = [njr.config["video_workflow"]["seed"] for njr in plan.njrs]
    assert all(isinstance(seed, int) and 0 <= seed < 2**31 for seed in seeds)
    assert len(set(seeds)) == 8  # independent, not one shared draw
    assert [job.seed for job in plan.jobs] == seeds  # the preview shows the very values

    controller.submit_batch(plan)
    admitted = [njr.config["video_workflow"]["seed"] for njr in service.calls[0]]
    assert admitted == seeds  # queueing never re-rolls


def test_review_lineage_is_preserved_and_content_hash_alone_invents_no_parent(tmp_path):
    controller, service = _stack(tmp_path)
    paths = _images(tmp_path, 2)
    selection = controller.select_batch_sources(
        [str(paths[0]), str(paths[1])],
        {str(paths[0]): {"source_job_id": "job-parent-1", "source_artifact_id": "art-9"}},
    )
    plan = controller.preview_batch(sources=selection.sources, form_data=_form())
    with_lineage, without = plan.njrs
    assert with_lineage.source.parent_job_id == "job-parent-1"
    assert with_lineage.source.parent_artifact_id == "art-9"
    assert without.source.parent_job_id is None and without.source.parent_artifact_id is None
    identity = dict(dict(without.provenance.metadata)["video_workflow"])["source_identity"]
    assert dict(identity)["original_sha256"] == _sha(paths[1])


def test_embedded_job_stamp_becomes_lineage_only_for_review_selections(tmp_path):
    from src.utils.image_metadata import ImageMetadataContractV26, write_image_metadata

    controller, _ = _stack(tmp_path)
    paths = _images(tmp_path, 2)
    for path in paths:
        assert write_image_metadata(path, {ImageMetadataContractV26.KEY_JOB_ID: "job-embedded"})
    names = [str(p) for p in paths]

    from_files = controller.preview_batch(
        sources=controller.select_batch_sources(names).sources, form_data=_form()
    )
    assert [n.source.parent_job_id for n in from_files.njrs] == [None, None]

    from_review = controller.preview_batch(
        sources=controller.select_batch_sources(names, review_origin=True).sources,
        form_data=_form(),
    )
    assert [n.source.parent_job_id for n in from_review.njrs] == ["job-embedded"] * 2
    identity = dict(dict(from_review.njrs[0].provenance.metadata)["video_workflow"])
    assert dict(identity["source_identity"])["source_job_id"] == "job-embedded"


def test_repeated_previews_reuse_prepared_sources(tmp_path):
    controller, _service = _stack(tmp_path)
    paths = _images(tmp_path, 3)
    selection = controller.select_batch_sources([str(p) for p in paths])
    first = controller.preview_batch(sources=selection.sources, form_data=_form())
    folder = tmp_path / "output" / "prepared_video_sources"
    before = sorted(p.name for p in folder.iterdir())

    second = controller.preview_batch(sources=selection.sources, form_data=_form())
    assert sorted(p.name for p in folder.iterdir()) == before  # no duplicates
    assert {row.preparation for row in second.assessment.rows} == {"reuse"}
    assert [j.prepared_path for j in first.jobs] == [j.prepared_path for j in second.jobs]
    assert first.batch_id != second.batch_id


def test_every_selectable_workflow_names_its_output_by_job_id(tmp_path):
    """Jobs of a batch may share a seed or even a prepared image; their artifacts still cannot
    collide because the executor-bound output name embeds the (unique) job id."""

    controller, _ = _stack(tmp_path)
    specs = controller._workflow_registry.list_specs_for_backend("comfy")
    assert specs
    for spec in specs:
        template = (spec.backend_defaults or {}).get("prompt_template") or {}
        prefixes = [
            str(node["inputs"]["filename_prefix"])
            for node in template.values()
            if isinstance(node, dict)
            and node.get("class_type") in {"SaveVideo", "StableNewSaveVideo"}
        ]
        assert prefixes, spec.workflow_id
        assert all("{{request.job_id}}" in prefix for prefix in prefixes), spec.workflow_id


# ------------------------------------------------------------------ stale-input refusal


def _expect_refused(controller, service, plan, *, match: str) -> None:
    with pytest.raises(BatchRefused, match=match):
        controller.submit_batch(plan)
    assert service.calls == []  # zero jobs were admitted


def test_source_replaced_with_different_bytes_is_refused(tmp_path):
    controller, service, paths, plan = _preview(tmp_path, 3)
    Image.new("RGB", (60, 90), "white").save(paths[1])
    _expect_refused(controller, service, plan, match="source image changed")


def test_same_size_same_mtime_source_replacement_is_refused(tmp_path):
    controller, service, paths, plan = _preview(tmp_path, 3)
    _same_size_replace(paths[2])
    _expect_refused(controller, service, plan, match="source image changed")


def test_prepared_source_tampering_is_refused(tmp_path):
    controller, service, _paths, plan = _preview(tmp_path, 3)
    _same_size_replace(Path(plan.jobs[0].prepared_path))
    _expect_refused(controller, service, plan, match="prepared source image changed")


def test_deleted_source_is_refused_as_unreadable(tmp_path):
    controller, service, paths, plan = _preview(tmp_path, 2)
    paths[0].unlink()
    _expect_refused(controller, service, plan, match="no longer readable")


def _drive_plan(tmp_path: Path, count: int = 6):
    controller, service = _stack(tmp_path)
    clip = tmp_path / "driving.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42 fake driving clip " * 8)
    form = {
        "workflow_id": WAN_ANIMATE2_DRIVE_ID,
        "workflow_version": WAN_ANIMATE2_CONTROLS_VERSION,
        "prompt": "Character appearance description: a woman in a navy top.",
        "negative_prompt": "",
        "pose_video_path": str(clip),
        "experimental_opt_in": True,
        "seed": "5",
        "operator_controls": {"pose_prompt": "A person steps left.", "pose_strength": "1"},
    }
    selection = controller.select_batch_sources([str(p) for p in _images(tmp_path, count)])
    plan = controller.preview_batch(sources=selection.sources, form_data=form)
    return controller, service, clip, plan


def test_changed_driving_video_is_refused(tmp_path):
    controller, service, clip, plan = _drive_plan(tmp_path)
    assert plan.eligible, plan.assessment.problems
    assert {njr.config["video_workflow"]["pose_video_sha256"] for njr in plan.njrs} == {_sha(clip)}
    _same_size_replace(clip)
    _expect_refused(controller, service, plan, match="driving video changed")


def test_shared_driving_video_is_hashed_once_per_phase_not_once_per_job(tmp_path, monkeypatch):
    import src.video.video_workflow_njr_builder as builder_module

    real = builder_module.sha256_file
    hashed: list[str] = []

    def counting(path):
        hashed.append(str(Path(path).name))
        return real(path)

    monkeypatch.setattr(builder_module, "sha256_file", counting)
    controller, service, _clip, plan = _drive_plan(tmp_path, count=8)
    assert plan.eligible
    assert hashed.count("driving.mp4") == 1  # freeze: one hash for eight jobs
    controller.submit_batch(plan)
    assert hashed.count("driving.mp4") == 2  # admission re-verified it once, not eight times
    assert len(service.calls) == 1


def _stub_builder(tmp_path: Path, **declared: Any):
    names = ("source_image", "prompt", "end_anchor", "mid_anchors", "depth_map", "seed")
    spec = SimpleNamespace(
        workflow_id="stub",
        workflow_version="1.0.0",
        display_name="Stub",
        backend_id="comfy",
        governance_state="approved",
        is_experimental=False,
        declared_input_names=names,
        required_input_names=(),
        accepted_controls=("source_image", "prompt_text", "end_anchor", "mid_anchors"),
        input_bindings=(),
        backend_defaults={},
    )
    registry = SimpleNamespace(get=lambda _id, _version=None: spec)
    return VideoWorkflowNjrBuilder(
        workflow_registry=registry, output_dir_provider=lambda: str(tmp_path / "out")
    )


@pytest.mark.parametrize("which", ["end anchor", "mid anchor 1", "depth map"])
def test_file_backed_anchor_and_depth_inputs_are_frozen_and_verified(tmp_path, which):
    builder = _stub_builder(tmp_path)
    source = _images(tmp_path, 1)[0]
    extras = _images(tmp_path, 3, folder="extras")
    form = {
        "workflow_id": "stub",
        "workflow_version": "1.0.0",
        "prompt": "motion",
        "end_anchor_path": str(extras[0]),
        "mid_anchor_paths": [str(extras[1])],
        "depth_input": {"mode": "upload", "path": str(extras[2])},
    }
    frozen = builder.freeze_inputs(source, form)
    labels = {label for label, _path, _sha in frozen.shared_files}
    assert labels == {"end anchor", "mid anchor 1", "depth map"}
    builder.verify_unchanged(frozen)  # unchanged: accepted

    target = {"end anchor": extras[0], "mid anchor 1": extras[1], "depth map": extras[2]}[which]
    _same_size_replace(target)
    with pytest.raises(ValueError, match=f"{which} changed"):
        builder.verify_unchanged(frozen)
    # A batch checks its shared inputs once, separately from each job's own files.
    builder.verify_unchanged(frozen, include_shared=False)
    shared = builder.freeze_shared_inputs({**form})
    assert {label for label, *_ in shared.files} == labels


def test_unused_anchor_fields_are_not_frozen_as_evidence(tmp_path):
    builder = _stub_builder(tmp_path)
    builder_spec = builder.spec_for({"workflow_id": "stub"})
    builder_spec.declared_input_names = ("source_image", "prompt", "seed")  # no anchors/depth
    source = _images(tmp_path, 1)[0]
    frozen = builder.freeze_inputs(
        source,
        {
            "workflow_id": "stub",
            "prompt": "x",
            "depth_input": {"mode": "upload", "path": str(source)},
        },
    )
    assert frozen.shared_files == ()


def test_unwritable_destination_probe_blocks(tmp_path, monkeypatch):
    import src.video.video_workflow_batch as batch_module

    def refuse(*_a, **_kw):
        raise PermissionError("access denied by ACL")

    monkeypatch.setattr(batch_module.tempfile, "TemporaryFile", refuse)
    controller, _ = _stack(tmp_path)
    selection = controller.select_batch_sources([str(p) for p in _images(tmp_path, 1)])
    plan = controller.preview_batch(sources=selection.sources, form_data=_form())
    assert not plan.eligible and "not writable" in plan.assessment.destination_error
    assert not (tmp_path / "output" / "prepared_video_sources").exists()  # nothing published


def test_a_folder_scan_that_cannot_finish_is_refused_not_returned_short(tmp_path, monkeypatch):
    import src.video.video_workflow_batch as batch_module

    root = tmp_path / "wide"
    (root / "a_noise").mkdir(parents=True)
    (root / "b_imgs").mkdir()
    for index in range(30):
        (root / "a_noise" / f"note_{index:02d}.txt").write_text("x")
    for index in range(10):
        Image.new("RGB", (8, 8), (index, 0, 0)).save(root / "b_imgs" / f"i{index}.png")

    assert len(scan_folder(root).sources) == 10  # a finished scan keeps every image

    monkeypatch.setattr(batch_module, "FOLDER_VISIT_LIMIT", 20)
    with pytest.raises(BatchRefused, match="without finishing.*incomplete"):
        scan_folder(root)  # previously: a quiet list of however many images came first

    monkeypatch.setattr(batch_module, "FOLDER_VISIT_LIMIT", 20000)
    monkeypatch.setattr(batch_module, "FOLDER_SCAN_LIMIT", 6)
    with pytest.raises(BatchRefused, match="at least 6 images"):
        scan_folder(root)


def test_an_unreadable_subfolder_refuses_the_scan_instead_of_omitting_its_images(
    tmp_path, monkeypatch
):
    import src.video.video_workflow_batch as batch_module

    root = tmp_path / "lib"
    (root / "locked").mkdir(parents=True)
    Image.new("RGB", (8, 8), "red").save(root / "open.png")
    Image.new("RGB", (8, 8), "blue").save(root / "locked" / "hidden.png")
    real_walk = os.walk

    def walk_with_denied_subfolder(top, onerror=None, followlinks=False):
        for dirpath, dirnames, filenames in real_walk(
            top, onerror=onerror, followlinks=followlinks
        ):
            if Path(dirpath).name == "locked":
                if onerror is not None:
                    onerror(PermissionError(13, "Access is denied", str(dirpath)))
                continue
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(batch_module.os, "walk", walk_with_denied_subfolder)
    with pytest.raises(BatchRefused, match="could not be read.*incomplete"):
        scan_folder(root)
    # Top-level only never enters the subfolder, so it is complete and says it is top-level.
    flat = scan_folder(root, recursive=False)
    assert [Path(s.path).name for s in flat.sources] == ["open.png"]
    assert "top level only" in flat.note


def test_linked_folder_loops_are_followed_once_and_never_duplicate_sources(tmp_path):
    root = tmp_path / "linked"
    (root / "real").mkdir(parents=True)
    Image.new("RGB", (8, 8), "red").save(root / "real" / "a.png")
    try:
        os.symlink(root, root / "real" / "loop", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this host")
    selection = scan_folder(root)
    assert [Path(s.path).name for s in selection.sources] == ["a.png"]


def test_anchor_and_depth_changes_are_refused_at_admission_not_only_by_the_builder(tmp_path):
    builder = _stub_builder(tmp_path)
    service = VideoWorkflowBatchService(builder)
    sources = select_sources([str(p) for p in _images(tmp_path, 2)]).sources
    extras = _images(tmp_path, 3, folder="extras")
    form = {
        "workflow_id": "stub",
        "workflow_version": "1.0.0",
        "prompt": "motion",
        "end_anchor_path": str(extras[0]),
        "mid_anchor_paths": [str(extras[1])],
        "depth_input": {"mode": "upload", "path": str(extras[2])},
    }
    for changed, label in (
        (extras[0], "end anchor"),
        (extras[1], "mid anchor 1"),
        (extras[2], "depth map"),
    ):
        plan = service.preview(form, sources)
        assert plan.eligible, plan.assessment.problems
        assert {name for name, *_ in plan.shared.files} == {
            "end anchor",
            "mid anchor 1",
            "depth map",
        }
        recorder = _JobService()
        original = changed.read_bytes()
        _same_size_replace(changed)
        try:
            with pytest.raises(BatchRefused, match=f"{label} changed"):
                service.admit(plan, recorder)
            assert recorder.calls == []
        finally:
            changed.write_bytes(original)


# ------------------------------------------------------------------ admission


def test_confirmed_batch_is_one_atomic_submit_call_with_identical_njrs(tmp_path):
    controller, service, _paths, plan = _preview(tmp_path, 5)
    result = controller.submit_batch(plan)
    assert len(service.calls) == 1
    assert tuple(service.calls[0]) == plan.njrs  # the very frozen records, in source order
    assert result.job_ids == plan.job_ids


def test_a_second_admission_of_the_same_plan_is_refused(tmp_path):
    controller, service, _paths, plan = _preview(tmp_path, 3)
    controller.submit_batch(plan)
    with pytest.raises(BatchRefused, match="already queued"):
        controller.submit_batch(plan)
    assert len(service.calls) == 1


def test_concurrent_admissions_of_one_plan_admit_exactly_once(tmp_path):
    controller, service, _paths, plan = _preview(tmp_path, 4)
    gate = threading.Barrier(6)
    outcomes: list[str] = []

    def attempt() -> None:
        gate.wait()
        try:
            controller.submit_batch(plan)
            outcomes.append("admitted")
        except BatchRefused:
            outcomes.append("refused")

    threads = [threading.Thread(target=attempt) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert sorted(outcomes) == ["admitted"] + ["refused"] * 5
    assert len(service.calls) == 1


def test_failed_admission_releases_the_plan_for_a_retry(tmp_path):
    class Flaky(_JobService):
        def __init__(self) -> None:
            super().__init__()
            self.fail = True

        def submit_njrs(self, njrs, policy):
            if self.fail:
                raise RuntimeError("repository unavailable")
            return super().submit_njrs(njrs, policy)

    flaky = Flaky()
    controller, service = _stack(tmp_path, flaky)
    selection = controller.select_batch_sources([str(p) for p in _images(tmp_path, 2)])
    plan = controller.preview_batch(sources=selection.sources, form_data=_form())
    with pytest.raises(BatchRefused, match="nothing was queued"):
        controller.submit_batch(plan)
    flaky.fail = False
    assert len(controller.submit_batch(plan).job_ids) == 2
    assert len(service.calls) == 1


def _real_service(tmp_path: Path, *, runner=None):
    repository = JobRepository(tmp_path / "queue.sqlite3")
    queue = JobQueue(repository=repository)
    service = JobService(queue, runner=runner) if runner is not None else JobService(queue)
    return service, queue, repository


def test_sqlite_rollback_admits_nothing_when_a_later_item_conflicts(tmp_path, monkeypatch):
    service, queue, repository = _real_service(tmp_path)
    controller, _ = _stack(tmp_path, service)
    selection = controller.select_batch_sources([str(p) for p in _images(tmp_path, 25)])
    plan = controller.preview_batch(sources=selection.sources, form_data=_form())
    assert plan.eligible

    original = repository._insert_job_submission
    inserted: list[str] = []

    def failing(*args, **kwargs):
        if len(inserted) == 24:
            import sqlite3

            raise sqlite3.IntegrityError("UNIQUE constraint failed: jobs.job_id")
        inserted.append("ok")
        return original(*args, **kwargs)

    monkeypatch.setattr(repository, "_insert_job_submission", failing)
    with pytest.raises(BatchRefused, match="nothing was queued"):
        controller.submit_batch(plan)
    assert len(inserted) == 24  # the conflict happened on the 25th insert
    assert queue.list_jobs() == []
    for job_id in plan.job_ids:
        assert repository.get_job_model(job_id) is None  # rolled back, not half-committed

    monkeypatch.setattr(repository, "_insert_job_submission", original)
    result = controller.submit_batch(plan)  # the same preview is admissible once the fault clears
    assert len(result.job_ids) == 25 and len(queue.list_jobs()) == 25


def test_runner_start_failure_after_durable_admission_reports_every_job(tmp_path, monkeypatch):
    service, queue, _repository = _real_service(tmp_path)
    service.auto_run_enabled = True

    def broken_start() -> None:
        raise RuntimeError("runner could not start")

    monkeypatch.setattr(service.runner, "start", broken_start)
    controller, _ = _stack(tmp_path, service)
    selection = controller.select_batch_sources([str(p) for p in _images(tmp_path, 4)])
    plan = controller.preview_batch(sources=selection.sources, form_data=_form())

    result = controller.submit_batch(plan)  # admitted jobs are reported, not rolled back

    assert result.job_ids == plan.job_ids and result.warning == ""
    assert {job.job_id for job in queue.list_jobs()} == set(plan.job_ids)
    assert all(queue.get_job(j).status is JobStatus.QUEUED for j in plan.job_ids)


def test_post_commit_callback_error_is_reported_as_admitted_not_rolled_back(tmp_path):
    class RaisesAfterCommit(_JobService):
        def __init__(self, queue: JobQueue) -> None:
            super().__init__()
            self.job_queue = queue

        def submit_njrs(self, njrs, policy):
            real = JobService(self.job_queue)
            real.submit_njrs(njrs, policy)
            raise RuntimeError("UI notification failed")

    repository = JobRepository(tmp_path / "q2.sqlite3")
    queue = JobQueue(repository=repository)
    controller, _ = _stack(tmp_path, RaisesAfterCommit(queue))
    selection = controller.select_batch_sources([str(p) for p in _images(tmp_path, 3)])
    plan = controller.preview_batch(sources=selection.sources, form_data=_form())
    result = controller.submit_batch(plan)
    assert result.job_ids == plan.job_ids
    assert "follow-up step reported" in result.warning


# ------------------------------------------------------------------ canonical-path integration


def test_twenty_five_video_jobs_queue_and_dispatch_sequentially_with_fake_backends(tmp_path):
    ran: list[str] = []
    active = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def run_callable(job):
        with lock:
            active["now"] += 1
            active["peak"] = max(active["peak"], active["now"])
            ran.append(job.job_id)
        time.sleep(0.001)
        with lock:
            active["now"] -= 1
        return {"success": True}

    repository = JobRepository(tmp_path / "queue.sqlite3")
    queue = JobQueue(repository=repository)
    runner = SingleNodeJobRunner(queue, run_callable, poll_interval=0.005)
    service = JobService(queue, runner=runner)
    service.auto_run_enabled = True
    controller, _ = _stack(tmp_path, service)
    images = _images(tmp_path, 25)
    selection = controller.select_batch_sources(
        [str(p) for p in images],
        {str(images[7]): {"source_job_id": "job-parent-7"}},
        review_origin=True,
    )
    plan = controller.preview_batch(sources=selection.sources, form_data=_form())
    assert plan.eligible

    try:
        result = controller.submit_batch(plan)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if all(
                queue.get_job(job_id).status is JobStatus.COMPLETED for job_id in result.job_ids
            ):
                break
            time.sleep(0.02)
        statuses = [queue.get_job(job_id).status for job_id in result.job_ids]
        assert statuses == [JobStatus.COMPLETED] * 25
    finally:
        runner.stop(timeout=5)

    assert repository.get_lineage(plan.job_ids[7])[0] == "job-parent-7"  # durable lineage
    assert repository.get_lineage(plan.job_ids[8])[0] is None  # nothing invented
    assert ran == list(plan.job_ids)  # one at a time, in source order
    assert active["peak"] == 1  # no new GPU parallelism
    for job_id in plan.job_ids:
        # PR-QUEUE-WEBUI-171 classifies these as independent video, so an outage hold applies
        # to WebUI work around them and never to them.
        assert classify_job(queue.get_job(job_id)).dependency is BackendDependency.INDEPENDENT_VIDEO
