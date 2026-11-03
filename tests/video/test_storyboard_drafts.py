"""Durable authoring drafts, never executable jobs; all storage and images are temporary."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from types import SimpleNamespace

import pytest

from src.gui.view_contracts.storyboard_contract import StoryboardSession
from src.gui.view_contracts.video_sequence_contract import SequenceSession
from src.video.sequence_shots import ShotDraft, build_sequence_intent
from src.video.storyboard import StoryboardDraft, StoryboardError
from src.video.storyboard_history import from_history
from src.video.storyboard_readiness import readiness, record_images, verify_images
from src.video.storyboard_store import StoryboardStore, read_draft
from tests.helpers.make_video_313 import TI2V_ID, make_app, make_image


@pytest.fixture
def authored(tmp_path):
    app, controller, service = make_app(tmp_path)
    form = {"workflow_id": TI2V_ID, "workflow_version": "1.3.0", "prompt": "waves", "seed": ""}
    draft = replace(
        StoryboardDraft.new("Walk"),
        source_path=make_image(tmp_path / "source.png", (480, 832)),
        workflow_id=TI2V_ID,
        workflow_version="1.3.0",
        settings=(("prompt", "waves"),),
        shots=(
            ShotDraft(prompt="waves", frame_count=17, seed="random"),
            ShotDraft(
                prompt="turns",
                frame_count=21,
                seed="",
                keyframe_path=make_image(tmp_path / "anchor.png", (480, 832), "red"),
                label="turn",
            ),
        ),
    )
    return SimpleNamespace(
        app=app, controller=controller, service=service, form=form, draft=record_images(draft)
    )


def test_storyboard_round_trip():
    draft = StoryboardDraft.new()
    assert StoryboardDraft.from_dict(draft.to_dict()) == draft


def test_full_round_trip_restart_save_as_and_export_import(authored, tmp_path):
    store = StoryboardStore(tmp_path / "library")
    draft = store.save(authored.draft)
    assert draft.revision == 1
    assert StoryboardStore(store.root).load(draft.storyboard_id) == draft
    duplicate = store.save(draft.duplicate())
    assert duplicate.storyboard_id != draft.storyboard_id and duplicate.revision == 1
    assert {s.shot_id for s in duplicate.shots}.isdisjoint(s.shot_id for s in draft.shots)
    assert [s.keyframe_sha256 for s in duplicate.shots] == [s.keyframe_sha256 for s in draft.shots]
    export = tmp_path / "export.json"
    store.export_json(draft, export)
    imported = store.import_json(export)
    assert imported.storyboard_id not in {draft.storyboard_id, duplicate.storyboard_id}
    assert store.load(draft.storyboard_id) == draft and read_draft(export) == draft
    assert authored.service.calls == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(schema="stablenew.storyboard-draft.v2"),
        lambda d: d.update(unrecognized={"must": "survive"}),
        lambda d: d["settings"].update(experimental_opt_in=True),
        lambda d: d.update(revision=True),
        lambda d: d.update(storyboard_id="../../source"),
        lambda d: d["shots"][0].update(frame_count="17"),
        lambda d: d["shots"][0].update(future="value"),
        lambda d: d["shots"][0].update(keyframe_sha256="invalid"),
    ],
)
def test_invalid_schema_fields_and_values_refuse_without_rewrite(authored, tmp_path, mutate):
    data = authored.draft.to_dict()
    mutate(data)
    path = tmp_path / "invalid.json"
    before = json.dumps(data).encode()
    path.write_bytes(before)
    with pytest.raises(StoryboardError):
        read_draft(path)
    assert path.read_bytes() == before


def test_malformed_file_and_atomic_failure_leave_previous_bytes(authored, tmp_path, monkeypatch):
    store = StoryboardStore(tmp_path)
    saved = store.save(authored.draft)
    path = tmp_path / f"{saved.storyboard_id}.json"
    before = path.read_bytes()

    def fail(*_args):
        raise OSError("injected replace failure")

    monkeypatch.setattr("src.utils.atomic_io._replace_with_retry", fail)
    with pytest.raises(OSError, match="replace failure"):
        store.save(replace(saved, title="new title"))
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp")) and not list(tmp_path.glob("*.lock"))
    path.write_bytes(b"{broken")
    with pytest.raises(StoryboardError, match="Malformed"):
        store.save(saved)
    assert path.read_bytes() == b"{broken"


def test_stale_revision_and_concurrent_save_never_lose_a_write(authored, tmp_path):
    store = StoryboardStore(tmp_path)
    saved = store.save(authored.draft)
    barrier = Barrier(2)

    def save(title):
        barrier.wait()
        try:
            return StoryboardStore(tmp_path).save(replace(saved, title=title))
        except StoryboardError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["one", "two"]))
    assert sum(isinstance(r, StoryboardDraft) for r in results) == 1
    winner = store.load(saved.storyboard_id)
    assert winner.revision == 2 and winner.title in {"one", "two"}
    with pytest.raises(StoryboardError, match="Revision conflict"):
        store.save(saved)


def test_export_never_overwrites_media_or_an_existing_json(authored, tmp_path):
    store = StoryboardStore(tmp_path / "library")
    image = tmp_path / "source.png"
    before = image.read_bytes()
    with pytest.raises(StoryboardError, match="new .json"):
        store.export_json(authored.draft, image)
    assert image.read_bytes() == before
    target = tmp_path / "clip.json"
    target.write_text("original")
    with pytest.raises(FileExistsError):
        store.export_json(authored.draft, target)
    assert target.read_text() == "original"


def test_reorder_duplicate_and_remove_preserve_shots_and_original_images(authored, tmp_path):
    draft = authored.draft
    original_bytes = {path: path.read_bytes() for path in tmp_path.glob("*.png")}
    moved = draft.move(1, -1)
    assert moved.shots == tuple(reversed(draft.shots))
    assert "unused keyframe" in " ".join(
        readiness(moved, authored.controller._workflow_registry, authored.form).problems
    )
    with pytest.raises(ValueError, match="unused keyframe"):
        build_sequence_intent(moved.shots)
    removed = replace(moved, shots=moved.shots[1:])
    assert len(removed.shots) == 1 and len(draft.shots) == 2
    assert all(path.read_bytes() == before for path, before in original_bytes.items())


def test_sources_and_anchors_must_be_explicitly_reaccepted(authored, tmp_path):
    draft = authored.draft
    make_image(tmp_path / "source.png", (480, 832), "green")
    assert record_images(draft).source_sha256 == draft.source_sha256
    with pytest.raises(StoryboardError, match="SHA-256 mismatch"):
        verify_images(draft)
    accepted = record_images(draft, accept_changed=True)
    assert accepted.source_sha256 != draft.source_sha256
    verify_images(accepted)
    (tmp_path / "source.png").unlink()
    (tmp_path / "anchor.png").unlink()
    projection = readiness(accepted, authored.controller._workflow_registry, authored.form)
    assert any("Source image: missing" in s for s in projection.problems)
    assert any("Shot 2 authored anchor: missing" in s for s in projection.problems)


def test_random_seed_and_summary_do_not_freeze_or_submit(authored):
    draft = authored.draft
    projection = readiness(draft, authored.controller._workflow_registry, authored.form)
    assert not projection.problems
    assert "38 native frames" in projection.summary and "approximately 1.58" in projection.summary
    assert "random at admission" in projection.summary
    assert [s.seed for s in draft.shots] == ["random", ""]
    assert authored.service.calls == []


def test_exact_order_one_submit_and_immutable_queued_plan(authored):
    draft = replace(
        authored.draft,
        shots=(
            replace(authored.draft.shots[1], keyframe_path="", keyframe_sha256=""),
            authored.draft.shots[0],
        ),
    )
    session = SequenceSession(get_controller=lambda: authored.controller)
    outcome = session.submit(
        source_image_path=draft.source_path,
        form_data=authored.form,
        shots=draft.shots,
        storyboard=draft,
    )
    assert outcome.ok and len(authored.service.calls) == 1
    njr = authored.service.submitted[0]
    plan = dict(njr.stage_chain[0].extra)["sequence_metadata"]
    before = repr(plan)
    assert [s["prompt"] for s in plan["segments"]] == ["turns", "waves"]
    assert all(isinstance(s["seed"], int) for s in plan["segments"])
    edited = replace(draft, shots=(replace(draft.shots[0], prompt="edited"), *draft.shots[1:]))
    assert edited.shots[0].prompt == "edited" and repr(plan) == before


@pytest.mark.parametrize("failure", ["missing", "changed", "length", "controls", "mismatch"])
def test_rejected_admission_submits_nothing(authored, tmp_path, failure):
    draft, form = authored.draft, dict(authored.form)
    shots = draft.shots
    if failure == "missing":
        (tmp_path / "anchor.png").unlink()
    elif failure == "changed":
        make_image(tmp_path / "source.png", (480, 832), "green")
    elif failure == "length":
        draft = replace(draft, shots=(replace(shots[0], frame_count=18), shots[1]))
        shots = draft.shots
    elif failure == "controls":
        form["pose_video_path"] = "must-not-be-dropped.mp4"
    else:
        shots = (replace(shots[0], prompt="different"), shots[1])
    outcome = SequenceSession(get_controller=lambda: authored.controller).submit(
        source_image_path=draft.source_path, form_data=form, shots=shots, storyboard=draft
    )
    assert not outcome.ok and authored.service.calls == []


def test_fun_control_incompatibility_is_visible_before_any_submission(authored):
    specs = authored.controller._workflow_registry.list_specs_for_backend("comfy")
    spec = next(s for s in specs if "fun" in s.workflow_id)
    draft = replace(
        authored.draft, workflow_id=spec.workflow_id, workflow_version=spec.workflow_version
    )
    projection = readiness(
        draft,
        authored.controller._workflow_registry,
        {**authored.form, "experimental_opt_in": True},
    )
    assert any("cannot supply" in p or "operator controls" in p for p in projection.problems)
    assert authored.service.calls == []


def test_draft_session_dirty_and_path_edit_does_not_reuse_an_old_hash(authored):
    session = StoryboardSession()
    session.opened(replace(authored.draft, revision=1))
    assert not session.dirty
    old = session.draft
    form = {**authored.form, **dict(old.settings)}
    session.capture(
        old.source_path,
        form,
        [old.shots[0], replace(old.shots[1], keyframe_path="new.png")],
        title="changed",
        clip_name=old.clip_name,
        notes=old.notes,
    )
    assert session.dirty and session.draft.shots[1].keyframe_sha256 == ""


def test_history_uses_canonical_frozen_plan_and_never_mutates_parent(authored, tmp_path):
    from src.queue.job_model import Job
    from src.queue.job_repository import JobRepository

    built = authored.controller.build_sequence_job(
        source_image_path=authored.draft.source_path,
        form_data=authored.form,
        sequence_intent=build_sequence_intent(authored.draft.shots),
        storyboard=authored.draft,
    )
    njr = built.njr
    repository = JobRepository(tmp_path / "jobs.sqlite")
    try:
        job = Job(job_id=njr.job_id)
        job._normalized_record = njr
        repository.record_job_submission(job)
        before = repository.get_job_model(job.job_id).snapshot
        draft = from_history(repository, job.job_id)
        another = from_history(repository, job.job_id)
        assert draft.storyboard_id != another.storyboard_id and draft.revision == 0
        plan = dict(njr.stage_chain[0].extra)["sequence_metadata"]
        assert draft.origin_plan_digest == plan["plan_digest"]
        assert draft.origin_job_id == job.job_id
        assert [s.seed for s in draft.shots] == [str(s["seed"]) for s in plan["segments"]]
        assert draft.source_sha256 == plan["source"]["sha256"]
        replace(draft, title="edit")
        assert repository.get_job_model(job.job_id).snapshot == before
        assert authored.service.calls == []
    finally:
        repository.close()


def test_invalid_history_cannot_invent_a_draft(authored):
    for repository in (None, SimpleNamespace(get_job_model=lambda _: None)):
        with pytest.raises(StoryboardError):
            from_history(repository, "missing")


@pytest.mark.parametrize("seed", ["random", "Random", " random "])
def test_explicit_first_shot_random_overrides_a_concrete_form_seed(authored, seed):
    shots = (replace(authored.draft.shots[0], seed=seed), authored.draft.shots[1])
    built = authored.controller.build_sequence_job(
        source_image_path=authored.draft.source_path,
        form_data={**authored.form, "seed": "7"},
        sequence_intent=build_sequence_intent(shots),
    )
    plan = dict(built.njr.stage_chain[0].extra)["sequence_metadata"]
    assert plan["segments"][0]["seed"] == built.seed


def test_duplicate_json_keys_refuse_without_rewriting(tmp_path):
    path = tmp_path / "duplicate.json"
    raw = b'{"schema":"future", "schema":"stablenew.storyboard-draft.v1"}'
    path.write_bytes(raw)
    with pytest.raises(StoryboardError, match="Duplicate JSON field"):
        read_draft(path)
    assert path.read_bytes() == raw


@pytest.mark.parametrize("seed", [0, "0"])
def test_typed_admission_preserves_explicit_zero_instead_of_inheriting(seed):
    from src.video.sequence_admission import freeze_sequence_plan
    from src.video.sequence_plan import STAGE_SVD_NATIVE

    plan = freeze_sequence_plan(
        {"segments": [{"seed": seed, "frame_count": 17}]},
        stage=STAGE_SVD_NATIVE,
        fps=6,
        segment_zero_seed=123,
        svd_max_frames=25,
        model_id="svd_xt",
    )
    assert plan.segments[0].seed == 0


@pytest.mark.parametrize(
    "tamper", ["digest", "schema", "missing_source", "mixed_workflow", "overlap"]
)
def test_unrepresentable_or_tampered_frozen_history_refuses(authored, tamper):
    from src.pipeline.njr_core_v26 import thaw_json
    from src.video.sequence_plan import SequencePlan

    built = authored.controller.build_sequence_job(
        source_image_path=authored.draft.source_path,
        form_data=authored.form,
        sequence_intent=build_sequence_intent(authored.draft.shots),
    )
    njr = built.njr
    stage = njr.stage_chain[0]
    config = thaw_json(stage.extra)
    plan = SequencePlan.from_dict(config["sequence_metadata"])
    if tamper == "digest":
        config["sequence_metadata"]["plan_digest"] = "0" * 64
    elif tamper == "schema":
        config["sequence_metadata"]["schema"] = "future-schema"
    elif tamper == "missing_source":
        config["sequence_metadata"] = replace(plan, source=None).to_dict()
    elif tamper == "mixed_workflow":
        segments = (plan.segments[0], replace(plan.segments[1], workflow_version="1.2.0"))
        config["sequence_metadata"] = replace(plan, segments=segments).to_dict()
    else:
        segments = (plan.segments[0], replace(plan.segments[1], overlap_frames=2))
        config["sequence_metadata"] = replace(plan, segments=segments).to_dict()
    changed = replace(njr, stages=(replace(stage, extra=config),))
    repository = SimpleNamespace(
        get_job_model=lambda _: SimpleNamespace(job_id=njr.job_id, _normalized_record=changed)
    )
    with pytest.raises(ValueError):
        from_history(repository, njr.job_id)
    assert authored.service.calls == []
