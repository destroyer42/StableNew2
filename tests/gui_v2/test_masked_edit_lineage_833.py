"""GP832-F3: a masked edit or canvas extension launched from History keeps the originating job as its parent.

Real Review tab (Tk), real History hand-off, real mask / outpaint dialogs driven through a synchronous worker, real
``JobService`` over temporary SQLite. No GPU, WebUI, model or runtime start. The lineage must bind to the exact selected
image and bytes; it must never transfer to another image or be invented for an image with no recorded job.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
from src.controller.masked_edit_service import bind_history_lineage, history_lineage_for
from src.gui.controllers.history_compare_service import has_recorded_parent
from src.gui.mask_editor_dialog import MaskEditorDialog
from src.gui.outpaint_dialog import OutpaintDialog
from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner
from src.image_backends import masked_inpaint as capability
from src.pipeline import image_edit_inputs as inputs
from src.queue.job_model import JobStatus
from tests.gui_v2 import test_history_iterate_service_610a as service_tests
from tests.gui_v2.test_history_iterate_service_610a import JOB_ID, Env
from tests.gui_v2.test_history_iterate_service_610a import _png as _small_png

env = service_tests.env  # the 610A Review + History fixture, reused as-is


def _png(path, *, job_id: str | None = JOB_ID, color=(10, 20, 30)) -> str:
    """The 610A synthetic image (embedded job id and metadata), large enough for the image-edit size bounds."""
    path = Path(path)
    _small_png(path, job_id=job_id, color=color)
    with Image.open(path) as small:
        info = dict(small.info)
    big = Image.new("RGB", (128, 128), color)
    from PIL.PngImagePlugin import PngInfo

    meta = PngInfo()
    for key, value in info.items():
        if isinstance(value, str):
            meta.add_text(key, value)
    big.save(path, pnginfo=meta)
    return str(path)


@pytest.fixture(autouse=True)
def forge_sdxl(env, tmp_path, monkeypatch):
    _png(env.image)  # recorded image: 128x128 with the same embedded identity
    monkeypatch.setattr(
        inputs, "default_snapshot_root", lambda: tmp_path / "state" / "image_edit_inputs"
    )
    monkeypatch.setattr(
        capability,
        "RegistryFamilyLookup",
        lambda: lambda _: CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ()),
    )
    env.app._build_reprocess_config = lambda _: {
        "model": "sdxl",
        "backend_options": {"image": {"backend_id": "forge_webui"}},
        "img2img": {"steps": 20, "sampler_name": "Euler", "scheduler": "Karras", "seed": 7},
    }


def _sync_runner() -> BackgroundWorkRunner:
    return BackgroundWorkRunner(
        spawn=lambda _, target: target(), dispatch=lambda callback: callback()
    )


def _sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _open_mask_editor(env: Env, tk_root, path: str | Path) -> MaskEditorDialog:
    """Open the editor exactly as Review's Edit Mask... does for ``path``."""
    editor = MaskEditorDialog(
        tk_root,
        source_path=Path(path),
        controller=env.app,
        runner=_sync_runner(),
        lineage=history_lineage_for(env.tab._active_handoff, Path(path)),
    )
    editor.update_idletasks()
    return editor


def _queue_edit(editor: MaskEditorDialog) -> str:
    assert editor.document is not None, editor.status.get()
    editor.document.paint((10, 10), (20, 20), 6)
    editor.prompt.insert("1.0", "add a red flower")
    editor.preview_button.invoke()
    assert editor._preview is not None, editor.status.get()
    editor.queue_button.invoke()
    assert "Queued frozen job" in editor.status.get(), editor.status.get()
    return editor._preview.job.job_id


def _finish(env: Env, job_id: str):
    env.repository.record_status_change(job_id, JobStatus.RUNNING, datetime.now())
    env.repository.record_status_change(
        job_id,
        JobStatus.COMPLETED,
        datetime.now(),
        result={"artifact": {"primary_path": env.image}, "image_count": 1},
    )
    return env.repository.get_job(job_id)


def _source(env: Env, job_id: str) -> dict:
    return env.repository.get_job(job_id).snapshot["normalized_job"]["source"]


@pytest.mark.gui
def test_masked_edit_from_history_records_the_originating_job_and_compare_is_offered(env, tk_root):
    assert env.iterate.edit_in_review(JOB_ID, lambda *_: True).done
    original = Path(env.image).read_bytes()
    digest = _sha(env.image)
    editor = _open_mask_editor(env, tk_root, env.image)
    try:
        child_id = _queue_edit(editor)
    finally:
        editor.destroy()

    assert child_id != JOB_ID
    queued = [row.job_id for row in env.repository.list_jobs()]
    assert queued == [child_id]  # a distinct job; the History job is not mutated or re-queued
    source = _source(env, child_id)
    assert source["parent_job_id"] == JOB_ID
    assert source["parent_artifact_id"] == f"sha256:{digest}"
    assert not has_recorded_parent(env.repository.get_job(child_id))  # not completed yet
    assert has_recorded_parent(_finish(env, child_id))
    assert Path(env.image).read_bytes() == original  # the original artifact is untouched


@pytest.mark.gui
def test_handoff_without_an_embedded_job_id_still_binds_to_the_verified_history_job(
    env, tk_root, tmp_path
):
    _png(tmp_path / "recorded.png", job_id=None)  # the image carries no job id of its own
    entry_image = env.image
    assert env.iterate.edit_in_review(JOB_ID, lambda *_: True).done
    editor = _open_mask_editor(env, tk_root, entry_image)
    try:
        child_id = _queue_edit(editor)
    finally:
        editor.destroy()
    assert _source(env, child_id)["parent_job_id"] == JOB_ID


@pytest.mark.gui
def test_a_standalone_image_gets_no_parent_job(env, tk_root, tmp_path):
    standalone = _png(tmp_path / "standalone.png", job_id=None)
    env.tab._set_selected_images([Path(standalone)])
    assert history_lineage_for(env.tab._active_handoff, Path(standalone)) is None
    editor = _open_mask_editor(env, tk_root, standalone)
    try:
        child_id = _queue_edit(editor)
    finally:
        editor.destroy()
    source = _source(env, child_id)
    assert source["parent_job_id"] is None
    assert not has_recorded_parent(_finish(env, child_id))


@pytest.mark.gui
def test_handoff_for_image_a_never_gives_its_parent_to_image_b(env, tk_root, tmp_path):
    assert env.iterate.edit_in_review(JOB_ID, lambda *_: True).done
    claim = history_lineage_for(env.tab._active_handoff, Path(env.image))
    assert claim is not None
    other = _png(tmp_path / "other.png", job_id=None, color=(90, 10, 10))
    # Review looks identity up by the exact selected path: B has no claim even while A's hand-off is active.
    assert history_lineage_for(env.tab._active_handoff, Path(other)) is None
    # A leaked claim presented with B is refused outright, never applied (path and digest both differ).
    with pytest.raises(ValueError, match="different image"):
        bind_history_lineage({}, source_path=other, source_sha256=_sha(other), lineage=claim)
    editor = MaskEditorDialog(
        tk_root, source_path=Path(other), controller=env.app, runner=_sync_runner(), lineage=claim
    )
    try:
        assert editor.document is None and "different image" in editor.status.get()
        assert env.repository.list_jobs() == []
    finally:
        editor.destroy()


@pytest.mark.gui
def test_a_new_review_selection_clears_the_handoff_claim(env, tmp_path):
    assert env.iterate.edit_in_review(JOB_ID, lambda *_: True).done
    assert history_lineage_for(env.tab._active_handoff, Path(env.image)) is not None
    env.tab._set_selected_images([Path(env.image)])  # same image re-selected by hand: a new context
    assert history_lineage_for(env.tab._active_handoff, Path(env.image)) is None


@pytest.mark.gui
def test_an_image_changed_after_the_handoff_refuses_the_editor_instead_of_reattributing(
    env, tk_root, tmp_path
):
    assert env.iterate.edit_in_review(JOB_ID, lambda *_: True).done
    claim = history_lineage_for(env.tab._active_handoff, Path(env.image))
    _png(tmp_path / "recorded.png", color=(200, 0, 0))  # same path and job id, different bytes
    editor = MaskEditorDialog(
        tk_root,
        source_path=Path(env.image),
        controller=env.app,
        runner=_sync_runner(),
        lineage=claim,
    )
    try:
        assert editor.document is None and "changed since" in editor.status.get()
        assert env.repository.list_jobs() == []
    finally:
        editor.destroy()


@pytest.mark.gui
def test_a_contradicting_embedded_job_id_is_refused(env, tk_root, tmp_path):
    assert env.iterate.edit_in_review(JOB_ID, lambda *_: True).done
    claim = deepcopy(history_lineage_for(env.tab._active_handoff, Path(env.image)))
    claim["source_artifact_id"] = "sha256:" + _sha(
        _png(tmp_path / "recorded.png", job_id="elsewhere")
    )
    with pytest.raises(ValueError, match="contradicts"):
        bind_history_lineage(
            {}, source_path=env.image, source_sha256=_sha(env.image), lineage=claim
        )


def test_forged_or_partial_claims_are_refused_and_no_claim_changes_nothing(env, tmp_path):
    baseline = {"model": "sdxl"}
    digest = _sha(env.image)
    assert (
        bind_history_lineage(baseline, source_path=env.image, source_sha256=digest, lineage=None)
        is baseline
    )
    unclaimed = {
        "source_job_id": "x",
        "source_artifact_id": f"sha256:{digest}",
        "source_path": env.image,
    }
    assert (
        bind_history_lineage(
            baseline, source_path=env.image, source_sha256=digest, lineage=unclaimed
        )
        is baseline
    )
    good = {
        "source_job_id": JOB_ID,
        "source_artifact_id": f"sha256:{digest}",
        "source_path": str(Path(env.image).resolve()),
        "history_iterate": {"job_id": JOB_ID, "choice": "edit_image"},
    }
    assert bind_history_lineage(
        baseline, source_path=env.image, source_sha256=digest, lineage=good
    ) == {
        "model": "sdxl",
        "job_id": JOB_ID,
    }
    for patch, message in (
        ({"source_job_id": "another-job"}, "does not name one job"),
        ({"source_artifact_id": ""}, "changed since"),
        ({"source_path": ""}, "different image"),
    ):
        with pytest.raises(ValueError, match=message):
            bind_history_lineage(
                baseline, source_path=env.image, source_sha256=digest, lineage={**good, **patch}
            )
    with pytest.raises(ValueError, match="contradicts"):
        bind_history_lineage(
            {"job_id": "someone-else"}, source_path=env.image, source_sha256=digest, lineage=good
        )


@pytest.mark.gui
def test_extend_canvas_from_history_shares_the_same_lineage(env, tk_root):
    assert env.iterate.edit_in_review(JOB_ID, lambda *_: True).done
    digest = _sha(env.image)
    dialog = OutpaintDialog(
        tk_root,
        source_path=Path(env.image),
        controller=env.app,
        runner=_sync_runner(),
        lineage=history_lineage_for(env.tab._active_handoff, Path(env.image)),
    )
    try:
        dialog.update_idletasks()
        assert dialog._baseline.get("job_id") == JOB_ID
        assert dialog._source_sha256 == digest
    finally:
        dialog.destroy()
    standalone = OutpaintDialog(
        tk_root, source_path=Path(env.image), controller=env.app, runner=_sync_runner()
    )
    try:
        assert "job_id" not in standalone._baseline
    finally:
        standalone.destroy()
