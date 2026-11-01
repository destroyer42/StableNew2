"""PR-HISTORY-610B: lineage, artifact identity and frozen-recipe comparison (no Tk; real SQLite in a temp dir)."""

from __future__ import annotations

import copy
import hashlib
import itertools
import threading
import time
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import pytest
from PIL import Image, PngImagePlugin

from src.gui.controllers.history_compare_service import (
    HistoryCompareService,
    has_recorded_parent,
    resolve_history_repository,
)
from src.gui.view_contracts import history_comparison_artifact as artifact_module
from src.gui.view_contracts.history_comparison_artifact import decode_verified_image
from src.gui_v2.history_compare_model import (
    ComparisonRefused,
    DifferenceState,
    observed_differences,
    recipe_differences,
)
from src.pipeline.history_variation_compiler import HistoryVariationDraft, compile_history_variation
from src.pipeline.job_models_v2 import SourceDescriptor, SourceKind
from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.queue.job_model import JobStatus
from src.queue.job_repository import JobRepository
from tests.helpers.njr_factory import make_pipeline_njr
from tests.queue.test_history_variation_lineage_610a import _job


def _complete(repo, job_id, path, **result):
    repo.record_status_change(job_id, JobStatus.RUNNING, datetime.now())
    payload = {"artifact": {"primary_path": str(path)}, "image_count": 1, **result}
    repo.record_status_change(job_id, JobStatus.COMPLETED, datetime.now(), result=payload)


@pytest.fixture
def family(tmp_path):
    """parent -> replay / variation / review children, replay -> grandchild, plus an unrelated look-alike."""

    repo = JobRepository(tmp_path / "jobs.sqlite3")
    paths = {}

    def image(job_id, colour):
        paths[job_id] = tmp_path / f"{job_id}.png"
        Image.new("RGB", (64, 48), colour).save(paths[job_id])

    for job_id, colour in (
        ("parent", "red"), ("replay", "green"), ("variation", "blue"), ("review", "yellow"),
        ("grandchild", "purple"), ("lookalike", "red"),
    ):  # fmt: skip
        image(job_id, colour)
    digest = hashlib.sha256(paths["parent"].read_bytes()).hexdigest()
    parent = make_pipeline_njr(
        job_id="parent", positive_prompt="a fox", config={"model": "sdxl", "steps": 20}
    )
    replay = compile_replay_intent(ReplayIntent(parent), id_fn=lambda: "replay")
    variation = compile_history_variation(
        HistoryVariationDraft.from_source(parent).with_edits(steps=33), id_fn=lambda: "variation"
    )
    review = replace(
        parent,
        job_id="review",
        source=SourceDescriptor(
            SourceKind.REPROCESS, parent_job_id="parent", parent_artifact_id=f"sha256:{digest}"
        ),
        provenance=replace(parent.provenance, metadata={"review_batch": {"batch_id": "t"}}),
    )
    grandchild = compile_replay_intent(ReplayIntent(replay), id_fn=lambda: "grandchild")
    lookalike = make_pipeline_njr(
        job_id="lookalike", positive_prompt="a fox", config={"model": "sdxl", "steps": 20}
    )
    jobs = (parent, replay, variation, review, grandchild, lookalike)
    repo.record_job_submissions([_job(njr) for njr in jobs])
    for njr in jobs:
        _complete(repo, njr.job_id, paths[njr.job_id])
    yield SimpleNamespace(
        repo=repo, paths=paths, digest=digest, parent=parent,
        service=HistoryCompareService(repo), tmp_path=tmp_path,
    )  # fmt: skip
    repo.close()


def _patch_entry(family, job_id, mutate):
    entry = family.repo.get_job(job_id)
    mutate(entry)
    original = family.repo.get_job
    family.repo.get_job = lambda requested: entry if requested == job_id else original(requested)
    return entry


# --- A. relationship and lineage -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("child", "kind"),
    [
        ("replay", "Exact History replay"),
        ("variation", "Edited History variation"),
        ("review", "Review-derived image"),
    ],
)
def test_each_supported_child_resolves_its_frozen_parent(family, child, kind):
    comparison = family.service.prepare(child)
    assert comparison.parent.job.job_id == "parent" and comparison.child.job.job_id == child
    assert comparison.relationship == kind
    assert comparison.parent.image.path == str(family.paths["parent"])
    assert comparison.child.image.path == str(family.paths[child])


def test_variation_is_found_although_replay_child_listing_excludes_it(family):
    # H2: list_replay_child_rows omits edited variations; the child's own parent_job_id is the authority.
    assert [r.job_id for r in family.repo.list_replay_child_rows(["parent"])] == ["replay"]
    assert family.service.prepare("variation").parent.job.job_id == "parent"


def test_grandchild_compares_with_immediate_parent_not_ancestor(family):
    comparison = family.service.prepare("grandchild")
    assert comparison.parent.job.job_id == "replay"


def test_root_job_and_look_alike_have_no_parent(family):
    for job_id in ("parent", "lookalike"):
        assert not has_recorded_parent(family.repo.get_job(job_id))
        with pytest.raises(ComparisonRefused, match="no recorded parent"):
            family.service.prepare(job_id)


def test_missing_child_and_missing_parent_are_refused(family):
    with pytest.raises(ComparisonRefused, match="selected job is no longer"):
        family.service.prepare("nope")
    family.repo._connection.execute("DELETE FROM jobs WHERE job_id = 'parent'")
    with pytest.raises(ComparisonRefused, match="parent job is no longer"):
        family.service.prepare("replay")


def test_snapshot_identity_mismatch_is_refused(family):
    _patch_entry(
        family, "review", lambda e: e.snapshot["normalized_job"].__setitem__("job_id", "other")
    )
    with pytest.raises(ComparisonRefused, match="different job"):
        family.service.prepare("review")


def test_parent_snapshot_identity_mismatch_is_refused(family):
    _patch_entry(
        family, "parent", lambda e: e.snapshot["normalized_job"].__setitem__("job_id", "other")
    )
    with pytest.raises(ComparisonRefused, match="parent job's stored snapshot belongs"):
        family.service.prepare("replay")


def test_contradictory_persisted_lineage_is_refused(family):
    family.repo._connection.execute(
        "UPDATE jobs SET parent_job_id = 'lookalike' WHERE job_id = 'variation'"
    )
    with pytest.raises(ComparisonRefused, match="Persisted lineage"):
        family.service.prepare("variation")


def test_contradictory_metadata_claims_are_refused(family):
    def poison(entry):
        entry.snapshot["normalized_job"]["source"]["metadata"]["parent_job_id"] = "lookalike"

    _patch_entry(family, "variation", poison)
    with pytest.raises(ComparisonRefused, match="claims contradict"):
        family.service.prepare("variation")


def test_incomplete_or_video_jobs_are_refused(family):
    original = family.repo.get_job
    family.repo.get_job = lambda job_id: (
        replace(original(job_id), status=JobStatus.FAILED)
        if job_id == "replay"
        else original(job_id)
    )
    with pytest.raises(ComparisonRefused, match="did not complete"):
        family.service.prepare("replay")

    def video(entry):
        entry.snapshot["normalized_job"]["workload_kind"] = "video"

    _patch_entry(family, "variation", video)
    with pytest.raises(ComparisonRefused):
        family.service.prepare("variation")


def test_repository_resolution_requires_the_canonical_reads():
    assert resolve_history_repository(None) is None
    assert resolve_history_repository(SimpleNamespace(job_service=SimpleNamespace())) is None


# --- B. artifact identity --------------------------------------------------------------------------


def test_sha256_parent_claim_is_verified_when_it_matches(family):
    comparison = family.service.prepare("review")
    assert comparison.parent_artifact_verified
    assert (
        "verified" in comparison.identity_note
        and "not independently" not in comparison.identity_note
    )


def test_missing_parent_claim_is_disclosed_never_treated_as_verified(family):
    comparison = family.service.prepare("replay")
    assert not comparison.parent_artifact_verified
    assert "not independently verified" in comparison.identity_note
    assert any("No SHA-256 parent-artifact claim" in note for note in comparison.limitations)


def test_parent_claim_mismatch_is_blocking(family):
    Image.new("RGB", (64, 48), "black").save(family.paths["parent"])
    with pytest.raises(ComparisonRefused, match="parent-artifact claim does not match"):
        family.service.prepare("review")


def test_non_sha256_claim_is_not_interpreted(family):
    def other_format(entry):
        entry.snapshot["normalized_job"]["source"]["parent_artifact_id"] = "uuid-123"

    _patch_entry(family, "review", other_format)
    family.repo._connection.execute(
        "UPDATE jobs SET parent_artifact_id = 'uuid-123' WHERE job_id = 'review'"
    )
    comparison = family.service.prepare("review")
    assert not comparison.parent_artifact_verified
    assert any("not a SHA-256 digest" in note for note in comparison.limitations)


@pytest.mark.parametrize(
    ("fault", "reason"),
    [
        ("missing", "missing"),
        ("multi", "multiple"),
        ("thumbnail", "thumbnail"),
        ("video", "video"),
        ("hash", "hash"),
        ("embedded", "embedded"),
        ("animated", "multi-frame"),
        ("corrupt", "corrupt"),
        ("oversized", "megapixel"),
    ],
)
@pytest.mark.parametrize("side", ["child", "parent"])
def test_bad_artifacts_are_refused_without_content_leaks(family, fault, reason, side, monkeypatch):
    job_id = "variation" if side == "child" else "parent"
    path = family.paths[job_id]
    result = {"artifact": {"primary_path": str(path)}, "image_count": 1}
    if fault == "missing":
        path.unlink()
    elif fault == "multi":
        result["artifact"]["output_paths"] = [str(family.paths["review"])]
    elif fault == "thumbnail":
        result = {"artifact": {"thumbnail_path": str(path)}}
    elif fault == "video":
        result["video_bundle"] = {"video_path": "private-secret.mp4"}
    elif fault == "hash":
        result["artifact"]["sha256"] = "0" * 64
    elif fault == "embedded":
        info = PngImagePlugin.PngInfo()
        info.add_text("stablenew:job_id", "private-secret")
        Image.new("RGB", (64, 48)).save(path, pnginfo=info)
    elif fault == "animated":
        Image.new("RGB", (64, 48), "red").save(
            path, format="PNG", save_all=True, append_images=[Image.new("RGB", (64, 48), "blue")]
        )
    elif fault == "corrupt":
        path.write_bytes(b"broken-private-secret")
    elif fault == "oversized":
        monkeypatch.setattr(artifact_module, "MAX_SOURCE_PIXELS", 10)
    family.repo.record_status_change(job_id, JobStatus.COMPLETED, datetime.now(), result=result)
    with pytest.raises(ComparisonRefused, match=reason) as error:
        family.service.prepare("variation")
    assert "private-secret" not in str(error.value)


def test_bytes_changed_between_verification_and_decode_are_never_displayed(family):
    comparison = family.service.prepare("variation")
    Image.new("RGB", (64, 48), "white").save(family.paths["variation"])
    with pytest.raises(ComparisonRefused, match="changed after verification"):
        decode_verified_image(comparison.child.image, threading.Event())


def test_unmodified_bytes_decode(family):
    comparison = family.service.prepare("variation")
    decoded = decode_verified_image(comparison.child.image, threading.Event())
    assert decoded.source_size == (64, 48)


def test_file_deleted_between_verification_and_decode_is_refused(family):
    comparison = family.service.prepare("variation")
    family.paths["variation"].unlink()
    with pytest.raises(ComparisonRefused, match="missing or unreadable"):
        decode_verified_image(comparison.child.image, threading.Event())


def test_preparing_never_writes_history(family):
    changes = family.repo._connection.total_changes
    for child in ("replay", "variation", "review"):
        family.service.prepare(child)
    assert family.repo._connection.total_changes == changes


# --- C. frozen recipe comparison ---------------------------------------------------------------------


def _rows(left, right):
    return {(r.group, r.field): r for r in recipe_differences(left, right)}


def _record(**config):
    return make_pipeline_njr(
        job_id="a", positive_prompt="a fox", config=config or {"steps": 20}
    ).to_dict()


def test_identical_settings_are_unchanged_and_ordering_is_deterministic():
    left, right = _record(model="sdxl", steps=20), _record(model="sdxl", steps=20)
    first = recipe_differences(left, right)
    assert first == recipe_differences(copy.deepcopy(left), copy.deepcopy(right))
    state = {(r.group, r.field): r.state for r in first}
    assert state[("Sampling", "Steps")] is DifferenceState.UNCHANGED
    assert state[("Prompts", "Positive prompt")] is DifferenceState.UNCHANGED
    runs = [group for group, _ in itertools.groupby(r.group for r in first)]
    assert len(runs) == len(set(runs))  # each group is one contiguous block


def test_prompt_seed_steps_cfg_dimensions_and_model_changes_are_detected():
    left, right = (
        _record(model="sdxl", steps=20, width=512),
        _record(model="flux", steps=33, width=768),
    )
    right["workload"]["positive_prompt"] = "a cat"
    right["provenance"]["seed"] = 7
    right["stages"][0]["cfg_scale"] = 4.5
    right["stages"][0]["steps"] = 33
    right["stages"][0]["model"] = "flux"
    right["workload"]["backend_options"] = {"image": {"backend_id": "comfy", "model_profile": "p"}}
    right["stages"][0]["vae"] = "ae"
    rows = _rows(left, right)
    for key in (
        ("Prompts", "Positive prompt"), ("Seed", "Requested seed (frozen)"), ("Sampling", "Steps"),
        ("Sampling", "CFG scale"), ("Dimensions", "Width"), ("Model", "Checkpoint"),
    ):  # fmt: skip
        assert rows[key].state is DifferenceState.CHANGED, key
    assert rows[("Model", "Backend")].state is DifferenceState.CHILD_ONLY
    assert rows[("Model", "VAE")].state is DifferenceState.CHILD_ONLY
    assert rows[("Model", "Model profile (as recorded)")].state is DifferenceState.CHILD_ONLY


def test_lora_and_embedding_differences_are_detected():
    left, right = _record(), _record()
    right["provenance"]["lora_tags"] = [{"name": "ink", "weight": 0.8}]
    right["provenance"]["positive_embeddings"] = ["pretty"]
    rows = _rows(left, right)
    assert rows[("LoRA", "LoRA tags")].state is DifferenceState.CHANGED
    assert rows[("Embeddings", "Positive embeddings")].state is DifferenceState.CHANGED
    assert rows[("Embeddings", "Negative embeddings")].state is DifferenceState.UNCHANGED


def test_different_stage_chains_stay_stage_specific():
    left, right = _record(), _record()
    right["stages"].append(
        {
            "stage_type": "upscale",
            "enabled": True,
            "steps": 12,
            "cfg_scale": None,
            "denoising_strength": 0.3,
            "sampler_name": None,
            "scheduler": None,
            "model": None,
            "vae": None,
            "extra": {"factor": 2},
        }  # fmt: skip
    )
    rows = _rows(left, right)
    assert rows[("Stages", "Enabled stage chain")].state is DifferenceState.CHANGED
    assert rows[("Stages", "upscale: steps")].state is DifferenceState.CHILD_ONLY
    assert rows[("Stages", "upscale: factor")].state is DifferenceState.CHILD_ONLY
    assert rows[("Stages", "txt2img: steps")].state is DifferenceState.UNCHANGED
    # the headline Steps value follows the NJR primary-stage convention and is not replaced by the upscale value
    assert rows[("Sampling", "Steps")].child == 20


def test_missing_optional_fields_are_not_guessed_and_zero_is_not_absent():
    left, right = _record(), _record()
    left["stages"][0]["cfg_scale"] = 0
    right["stages"][0]["cfg_scale"] = None
    del right["workload"]["backend_options"]
    rows = _rows(left, right)
    assert rows[("Sampling", "CFG scale")].state is DifferenceState.PARENT_ONLY
    assert rows[("Model", "Backend")].state is DifferenceState.NOT_RECORDED
    assert rows[("Sampling", "Scheduler")].state is DifferenceState.NOT_RECORDED
    assert rows[("Sampling", "Scheduler")].parent_recorded is False


def test_incompatible_value_types_are_not_comparable():
    left, right = _record(), _record()
    left["workload"]["config"]["custom"] = "1"
    right["workload"]["config"]["custom"] = 1
    assert (
        _rows(left, right)[("Other frozen settings", "custom")].state
        is DifferenceState.NOT_COMPARABLE
    )


def test_frozen_requested_seed_and_observed_seed_are_separate_evidence():
    left, right = _record(), _record()
    right["provenance"]["seed"] = -1
    rows = _rows(left, right)
    assert rows[("Seed", "Requested seed (frozen)")].evidence == "frozen"
    observed = observed_differences(
        {"metadata": {"seeds": {"final_seed": 5}}}, {"metadata": {"seeds": {"final_seed": 9}}},
        (64, 48), (64, 48),
    )  # fmt: skip
    seed = observed[0]
    assert (seed.evidence, seed.state, seed.parent, seed.child) == (
        "observed",
        DifferenceState.CHANGED,
        5,
        9,
    )
    assert observed[1].state is DifferenceState.UNCHANGED
    assert observed_differences(None, None, None, None)[0].state is DifferenceState.NOT_RECORDED


def test_values_come_from_the_two_recorded_jobs_only(family):
    # The service takes no application state: every value is read back from the stored parent and child.
    steps = next(r for r in family.service.prepare("variation").differences if r.field == "Steps")
    assert (steps.parent, steps.child, steps.state) == (20, 33, DifferenceState.CHANGED)
    model = next(
        r for r in family.service.prepare("variation").differences if r.field == "Checkpoint"
    )
    assert (model.parent, model.child, model.state) == ("sdxl", "sdxl", DifferenceState.UNCHANGED)


def _hydrate(family, job_id):
    from src.controller.pipeline_controller_services.history_handoff_service import (
        HistoryHandoffService,
    )

    return HistoryHandoffService().hydrate_njr_from_snapshot(family.repo.get_job(job_id).snapshot)


def _add_completed(family, *njrs):
    family.repo.record_job_submissions([_job(njr) for njr in njrs])
    for njr in njrs:
        path = family.tmp_path / f"{njr.job_id}.png"
        Image.new("RGB", (64, 48), "orange").save(path)
        family.paths[njr.job_id] = path
        _complete(family.repo, njr.job_id, path)


def test_exact_replay_of_a_review_child_inherits_its_claims_without_contradiction(family):
    # Replay copies the review child's workload/provenance metadata, which names the review child's own parent.
    base = _hydrate(family, "review")
    claims = {"parent_job_id": "parent", "parent_artifact_id": f"sha256:{family.digest}"}
    review2 = replace(
        base,
        job_id="review2",
        workload=replace(base.workload, metadata={**dict(base.workload.metadata), **claims}),
        provenance=replace(base.provenance, metadata={**dict(base.provenance.metadata), **claims}),
    )
    replayed = compile_replay_intent(ReplayIntent(review2), id_fn=lambda: "review2-replay")
    _add_completed(family, review2, replayed)
    comparison = family.service.prepare("review2-replay")
    assert comparison.parent.job.job_id == "review2"
    assert comparison.relationship == "Exact History replay"
    assert family.service.prepare("review2").parent.job.job_id == "parent"


def test_exact_replay_of_a_variation_is_not_labelled_an_edited_variation(family):
    replayed = compile_replay_intent(
        ReplayIntent(_hydrate(family, "variation")), id_fn=lambda: "variation-replay"
    )
    _add_completed(family, replayed)
    assert family.service.prepare("variation").relationship == "Edited History variation"
    comparison = family.service.prepare("variation-replay")
    assert comparison.parent.job.job_id == "variation"
    assert comparison.relationship == "Exact History replay"


def test_stored_null_variants_do_not_break_artifact_verification(family):
    _patch_entry(family, "variation", lambda entry: entry.result.__setitem__("variants", None))
    assert family.service.prepare("variation").child.job.job_id == "variation"


def test_oversized_frozen_config_is_capped_with_a_disclosed_limitation(family):
    def huge(entry):
        config = entry.snapshot["normalized_job"]["workload"]["config"]
        config.update({f"k{index:04d}": index for index in range(900)})

    _patch_entry(family, "variation", huge)
    comparison = family.service.prepare("variation")
    assert len(comparison.differences) == 600
    assert comparison.differences[-1].evidence == "observed"  # observed evidence survives the cap
    assert any("Display budget" in note for note in comparison.limitations)


def test_repeated_prepare_is_identical(family):
    first = family.service.prepare("review").differences
    assert first == family.service.prepare("review").differences


# --- D. Tk viewer and both History entry points ------------------------------------------------------


def _pump(root, predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)
    root.update()
    assert predicate()


@pytest.fixture
def threaded_work(monkeypatch):
    """The suite default runs edit work inline; ordering/late-delivery evidence needs real worker threads."""

    from src.gui.view_contracts import edit_work_runner

    monkeypatch.setattr(edit_work_runner, "coordinator_factory", edit_work_runner._tk_coordinator)


def _images_ready(dialog):
    return (
        dialog.comparison is not None
        and dialog.parent_view._image is not None
        and dialog.child_view._image is not None
    )


def _controller(family, state=None):
    return SimpleNamespace(
        job_service=SimpleNamespace(history_store=family.repo),
        app_state=state,
        pipeline_controller=SimpleNamespace(),
    )


def _explicit_child_prompt(family):
    def explicit(entry):
        entry.snapshot["normalized_job"]["workload"]["positive_prompt"] = "nude portrait"

    _patch_entry(family, "variation", explicit)


def test_compare_action_is_offered_for_children_only_on_both_surfaces(tk_root, family):
    from src.gui.app_state_v2 import AppStateV2
    from src.gui.history_browser_panel_v2 import HistoryBrowserPanelV2
    from src.gui.job_history_panel_v2 import JobHistoryPanelV2

    state = AppStateV2()
    state.set_history_items([family.repo.get_job(j) for j in ("variation", "parent")])
    controller = _controller(family, state)
    compact = JobHistoryPanelV2(tk_root, controller=controller, app_state=state)
    browser = HistoryBrowserPanelV2(
        tk_root, controller=controller, search=family.repo.query_history
    )
    _pump(tk_root, lambda: len(browser._entries) >= 6)
    bare = JobHistoryPanelV2(tk_root, app_state=state)
    for panel in (compact, browser):
        assert panel._history_action_state(family.repo.get_job("variation")).compare
        assert not panel._history_action_state(family.repo.get_job("parent")).compare
        assert panel.compare_btn.winfo_manager()  # placed in the wrapping action bar
        for job_id, expected in (("variation", "normal"), ("parent", "disabled")):
            item = next(k for k, v in panel._item_to_job.items() if v == job_id)
            panel.history_tree.selection_set(item)
            panel._on_select()
            assert str(panel.compare_btn.cget("state")) == expected
    assert not bare._history_action_state(family.repo.get_job("variation")).compare  # no repository
    for panel in (compact, browser, bare):
        panel.destroy()


def test_viewer_puts_parent_left_child_right_and_changes_nothing(tk_root, family, inline_edit_work):
    from src.gui.app_state_v2 import AppStateV2
    from src.gui.history_compare_dialog import HistoryCompareDialog

    state = AppStateV2()
    state.begin_history_variation(HistoryVariationDraft.from_source(family.parent))
    draft = state.job_draft
    changes = family.repo._connection.total_changes
    dialog = HistoryCompareDialog(
        tk_root, repository=family.repo, child_id="variation", app_state=state
    )
    _pump(tk_root, lambda: _images_ready(dialog))
    assert dialog.parent_view.current_path() == str(family.paths["parent"])
    assert dialog.child_view.current_path() == str(family.paths["variation"])
    assert dialog.parent_view.grid_info()["column"] < dialog.child_view.grid_info()["column"]
    assert "parent" in dialog.parent_title_var.get() and "variation" in dialog.child_title_var.get()
    assert "not independently verified" in dialog.identity_var.get()
    rows = [dialog.tree.item(i, "values") for i in dialog.tree.get_children()]
    steps = next(r for r in rows if r[0] == "Steps")
    assert tuple(steps[1:]) == ("changed", "20", "33")
    assert any(r[0].startswith("— Observed results") for r in rows)
    dialog.destroy()
    assert family.repo._connection.total_changes == changes and state.job_draft is draft


def test_refusal_is_shown_instead_of_images(tk_root, family, inline_edit_work):
    from src.gui.history_compare_dialog import HistoryCompareDialog

    dialog = HistoryCompareDialog(tk_root, repository=family.repo, child_id="parent")
    _pump(tk_root, lambda: "no recorded parent" in dialog.status_var.get())
    assert dialog.comparison is None and dialog.parent_view.current_path() is None
    dialog.destroy()


def test_new_selection_supersedes_a_slow_older_request(tk_root, family, threaded_work, monkeypatch):
    from src.gui.history_compare_dialog import HistoryCompareDialog

    started, release = threading.Event(), threading.Event()
    original = HistoryCompareService.prepare

    def slow_for_replay(self, child_id):
        if child_id == "replay":
            started.set()
            assert release.wait(8)
        return original(self, child_id)

    monkeypatch.setattr(HistoryCompareService, "prepare", slow_for_replay)
    dialog = HistoryCompareDialog(tk_root, repository=family.repo, child_id="replay")
    _pump(tk_root, started.is_set)
    dialog.load("variation")
    release.set()
    _pump(tk_root, lambda: _images_ready(dialog))
    for _ in range(20):  # a late replay result must never replace the newer selection
        tk_root.update()
        time.sleep(0.01)
    assert dialog.comparison.child.job.job_id == "variation"
    assert dialog.child_view.current_path() == str(family.paths["variation"])
    dialog.destroy()


def test_closing_while_work_is_pending_drops_delivery(tk_root, family, threaded_work, monkeypatch):
    from src.gui.history_compare_dialog import HistoryCompareDialog

    started, release = threading.Event(), threading.Event()
    original = HistoryCompareService.prepare
    delivered = []

    def slow(self, child_id):
        started.set()
        assert release.wait(8)
        return original(self, child_id)

    monkeypatch.setattr(HistoryCompareService, "prepare", slow)
    dialog = HistoryCompareDialog(tk_root, repository=family.repo, child_id="variation")
    dialog._ready = lambda *args: delivered.append(args)  # would be a post-destroy Tk mutation
    for _ in range(5):  # repeated requests coalesce on one key instead of piling up workers
        dialog.load("variation")
    _pump(tk_root, started.is_set)
    work = dialog._work
    dialog.destroy()
    release.set()
    _pump(tk_root, lambda: not work.metrics()["inflight"])
    assert delivered == [] and work.closed


def test_visibility_modes_redact_text_and_hide_only_the_restricted_side(
    tk_root, family, inline_edit_work
):
    from src.controller.content_visibility_resolver import REDACTED_TEXT
    from src.gui.app_state_v2 import AppStateV2
    from src.gui.history_compare_dialog import HistoryCompareDialog

    _explicit_child_prompt(family)
    state = AppStateV2()
    state.set_content_visibility_mode("sfw")
    dialog = HistoryCompareDialog(
        tk_root, repository=family.repo, child_id="variation", app_state=state
    )
    _pump(tk_root, lambda: dialog.comparison is not None)

    def shown():
        return [dialog.tree.item(i, "values") for i in dialog.tree.get_children()]

    def prompt_row():
        return next(r for r in shown() if r[0] == "Positive prompt")

    assert prompt_row()[2] == "a fox" and prompt_row()[3] == REDACTED_TEXT
    assert prompt_row()[1] == "changed"  # the change is disclosed without disclosing the text
    assert "nude" not in " ".join(" ".join(map(str, r)) for r in shown())
    assert dialog.child_view.model.eligible is False and dialog.parent_view.model.eligible is True
    state.set_content_visibility_mode("nsfw")
    _pump(tk_root, lambda: prompt_row()[3] == "nude portrait")
    assert dialog.child_view.model.eligible is True
    state.set_content_visibility_mode("sfw")
    _pump(tk_root, lambda: prompt_row()[3] == REDACTED_TEXT)
    assert dialog.child_view.model.eligible is False
    dialog.destroy()


def test_late_decode_after_content_becomes_hidden_is_not_shown(
    tk_root, family, threaded_work, monkeypatch
):
    from src.gui import history_compare_dialog as dialog_module
    from src.gui.app_state_v2 import AppStateV2

    _explicit_child_prompt(family)
    child_path = str(family.paths["variation"])
    reached, release = threading.Event(), threading.Event()
    original = dialog_module.decode_verified_image

    def gated(expected, cancel):
        if expected.path == child_path:
            reached.set()
            assert release.wait(8)
        return original(expected, cancel)

    monkeypatch.setattr(dialog_module, "decode_verified_image", gated)
    state = AppStateV2()
    state.set_content_visibility_mode("nsfw")
    dialog = dialog_module.HistoryCompareDialog(
        tk_root, repository=family.repo, child_id="variation", app_state=state
    )
    _pump(tk_root, reached.is_set)
    state.set_content_visibility_mode("sfw")
    _pump(tk_root, lambda: dialog.child_view.model.eligible is False)
    release.set()
    for _ in range(30):
        tk_root.update()
        time.sleep(0.01)
    assert dialog.child_view._image is None and dialog.child_view._photo_image is None
    dialog.destroy()


def test_viewer_images_do_not_follow_the_main_window_workspace_tabs(
    tk_root, family, inline_edit_work
):
    from tkinter import ttk

    from src.gui.history_compare_dialog import HistoryCompareDialog
    from src.gui.widgets.media_inspector import MediaInspector

    notebook = ttk.Notebook(tk_root)
    page = ttk.Frame(notebook)
    notebook.add(page, text="Pipeline")
    notebook.add(ttk.Frame(notebook), text="Other")
    followed = MediaInspector(page)  # control: an embedded inspector is hidden with its tab
    dialog = HistoryCompareDialog(page, repository=family.repo, child_id="variation")
    _pump(tk_root, lambda: _images_ready(dialog))
    assert followed._workspace_hosts
    assert dialog.parent_view._workspace_hosts == [] and dialog.child_view._workspace_hosts == []
    notebook.select(1)
    tk_root.update()
    assert dialog.parent_view.model.active and dialog.child_view.model.active
    dialog.destroy()
    followed.destroy()
    notebook.destroy()


def test_restricted_frozen_config_text_hides_its_side_even_with_clean_prompts(
    tk_root, family, inline_edit_work
):
    from src.gui.app_state_v2 import AppStateV2
    from src.gui.history_compare_dialog import HistoryCompareDialog

    def restricted_config(entry):
        entry.snapshot["normalized_job"]["workload"]["config"]["prompt"] = "nude portrait"

    _patch_entry(family, "variation", restricted_config)
    state = AppStateV2()
    state.set_content_visibility_mode("sfw")
    dialog = HistoryCompareDialog(
        tk_root, repository=family.repo, child_id="variation", app_state=state
    )
    _pump(tk_root, lambda: dialog.comparison is not None)
    shown = " ".join(
        " ".join(map(str, dialog.tree.item(i, "values"))) for i in dialog.tree.get_children()
    )
    assert "nude" not in shown
    assert dialog.child_view.model.eligible is False and dialog.parent_view.model.eligible is True
    dialog.destroy()


def test_panel_reuses_one_viewer_and_leaves_selection_and_filters_alone(
    tk_root, family, inline_edit_work
):
    from src.gui.app_state_v2 import AppStateV2
    from src.gui.history_browser_panel_v2 import HistoryBrowserPanelV2

    controller = _controller(family, AppStateV2())
    browser = HistoryBrowserPanelV2(
        tk_root, controller=controller, search=family.repo.query_history
    )
    _pump(tk_root, lambda: len(browser._entries) >= 6)
    browser._text_var.set("pending filter edit")
    windows = []
    for job_id in ("variation", "review"):
        item = next(k for k, v in browser._item_to_job.items() if v == job_id)
        browser.history_tree.selection_set(item)
        browser._on_select()
        selection = browser.history_tree.selection()
        browser._on_compare()
        window = browser._compare_window
        windows.append(window)
        _pump(
            tk_root, lambda w=window, j=job_id: w.comparison and w.comparison.child.job.job_id == j
        )
        assert browser.history_tree.selection() == selection
    assert windows[0] is windows[1] and browser._text_var.get() == "pending filter edit"
    windows[0].destroy()
    browser.destroy()


# --- E. agent-rule documentation -----------------------------------------------------------------------


def test_agents_md_carries_the_session_boundary_rule_once_and_the_model_agrees():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.count("### Work-package session boundaries and token discipline") == 1
    assert agents.count("starts in a fresh top-level Claude Code or Codex session") == 1
    assert "docs/AGENT_OPERATING_MODEL.md" in agents and "docs/AI_MODEL_SELECTION.md" in agents
    operating_model = (root / "docs" / "AGENT_OPERATING_MODEL.md").read_text(encoding="utf-8")
    assert "One session per work package" in operating_model
    assert "Start a fresh session at the package boundary" in operating_model
