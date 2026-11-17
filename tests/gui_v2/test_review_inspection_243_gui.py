"""AI-VL-243: "Save inspection" in Inspect & Improve, driven through the real Tk Review tab.

Synthetic images only; the Learning evidence writer is a temporary file; background work is run by the manual registry
so the test decides when each worker runs. No backend, job queue, model or GPU is touched, and every dialog is patched.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.view_contracts.review_workspace_contract import item_key
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.learning.learning_record import LearningRecordWriter
from src.review.findings import Category, Certainty, Confirmation, Severity
from src.utils.image_metadata import build_contract_kv, write_image_metadata
from tests.gui_v2.edit_work_helpers import use_manual_registry
from tests.review.test_guided_review_400 import CONFIG, MODEL, make_image

OBSERVATION = "zz private observation words zz"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(writer: LearningRecordWriter) -> list[dict]:
    if not writer.records_path.exists():
        return []
    return [json.loads(line) for line in writer.records_path.read_text("utf-8").splitlines()]


@pytest.fixture
def review(tk_root, tmp_path, monkeypatch):
    registry = use_manual_registry(monkeypatch)
    for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel"):
        monkeypatch.setattr(f"src.gui.views.review_tab_frame_v2.messagebox.{name}", Mock())
    monkeypatch.setattr("src.gui.guided_review_dialog.configured_image_backend_id", lambda: "x")
    controller = SimpleNamespace(
        resource_service=SimpleNamespace(client=SimpleNamespace(get_scripts=Mock(), base_url="")),
        _extract_reprocess_baseline_from_image=lambda _: {"model": MODEL},
        _build_reprocess_config=lambda _: CONFIG,
        submit_review_reprocess_batch_async=Mock(),
        preview_review_reprocess_batch=Mock(),
        enqueue=Mock(),
    )
    writer = LearningRecordWriter(tmp_path / "evidence.jsonl")
    tab = ReviewTabFrame(tk_root, app_state=AppStateV2(), app_controller=controller)
    tab._resolve_evidence_writer = lambda: writer  # type: ignore[method-assign]
    sources = [make_image(tmp_path / f"source-{index}.png", 2) for index in range(2)]
    tab._set_selected_images(sources)
    registry.run_all()
    tab.preview.model.visibility(active=True, shown=True)
    yield SimpleNamespace(
        tab=tab, registry=registry, controller=controller, writer=writer, sources=sources
    )
    tab.destroy()


def _open(review):
    review.tab._open_guided_review()
    dialog = review.tab._inspection
    assert dialog is not None
    review.registry.run_all()
    dialog.after_view.model.visibility(active=True, shown=True)
    return dialog


def _record(dialog, category=Category.HANDS, region=(7, 7, 19, 21), *, severity=None, **kw):
    dialog._new_finding()
    dialog._select_region(region)
    dialog._category.set(category)
    dialog._certainty.set(kw.get("certainty", Certainty.CLEAR))
    dialog._confirmation.set(kw.get("confirmation", Confirmation.CONFIRMED))
    dialog._severity.set(severity or "Not recorded")
    dialog._observation.delete("1.0", "end")
    dialog._observation.insert("1.0", OBSERVATION)
    dialog._record()


def _enabled(button) -> bool:
    return button.instate(["!disabled"])


def _row_text(review, path) -> str:
    session = review.tab._session
    return session.row_text(session.item(item_key(path)))


# ------------------------------------------------------------------------------------------------------------ save


def test_save_inspection_saves_confirmed_findings_without_a_job_or_a_file_change(review):
    source = review.sources[0]
    before = (source.read_bytes(), source.stat().st_mtime_ns)
    dialog = _open(review)
    assert not _enabled(dialog._inspection_button) and _enabled(dialog._clean_button)
    _record(dialog, Category.HANDS, (7, 7, 19, 21), severity="major")
    _record(
        dialog, Category.FACE, None, confirmation=Confirmation.UNCERTAIN
    )  # not confirmed: never stored
    assert _enabled(dialog._inspection_button) and not _enabled(dialog._clean_button)
    dialog._subjects.set("2")
    dialog._save_inspection("defects_confirmed")
    assert _rows(review.writer) == []  # nothing happens until the worker runs
    review.registry.run_all()
    (row,) = _rows(review.writer)
    metadata = row["metadata"]
    assert (
        metadata["source"] == "review_tab_inspection" and metadata["verdict"] == "defects_confirmed"
    )
    assert metadata["artifact_sha256"] == _sha(source) and metadata["subject_count"] == 2
    assert metadata["findings"] == [
        {
            "category": "Hands",
            "region": [7, 7, 19, 21],
            "certainty": "Clear to the operator",
            "severity": "major",
        }
    ]
    assert OBSERVATION not in review.writer.records_path.read_text("utf-8")
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before
    assert "no job was queued" in dialog._status.get()
    # no correction, preview or queue admission happened
    review.controller.submit_review_reprocess_batch_async.assert_not_called()
    review.controller.preview_review_reprocess_batch.assert_not_called()
    review.controller.enqueue.assert_not_called()
    # the Review workspace shows the verdict only, on the image's one-line row
    assert "(inspected: defects)" in _row_text(review, source)
    assert "Hands" not in _row_text(review, source) and "major" not in _row_text(review, source)
    assert "Saved inspection" in review.tab._feedback_status_var.get()
    # it is not a rating, and the other image is untouched
    assert review.tab._feedback_undo_stack == []
    assert "inspected" not in _row_text(review, review.sources[1])
    assert dialog.winfo_exists()  # the dialog stays open so a correction can still be drafted


def test_no_defect_seen_is_an_explicit_choice_saved_as_clean(review):
    dialog = _open(review)
    assert not _enabled(dialog._inspection_button)
    dialog._save_inspection(
        "defects_confirmed"
    )  # no confirmed finding: refused with a plain message
    review.registry.run_all()
    assert _rows(review.writer) == [] and "Confirm at least one finding" in dialog._status.get()
    dialog._save_inspection("no_defect_seen")
    review.registry.run_all()
    (row,) = _rows(review.writer)
    assert row["metadata"]["verdict"] == "no_defect_seen"
    assert row["metadata"]["findings"] == [] and row["metadata"]["subject_count"] is None
    assert "(inspected: no defect)" in _row_text(review, review.sources[0])


def test_no_defect_seen_is_refused_beside_a_confirmed_or_uncertain_finding(review):
    dialog = _open(review)
    _record(dialog)
    assert not _enabled(dialog._clean_button)
    dialog._save_inspection("no_defect_seen")
    assert "confirmed finding" in dialog._status.get()
    dialog._findings.clear()
    _record(dialog, confirmation=Confirmation.UNCERTAIN)
    dialog._save_inspection("no_defect_seen")
    assert "Uncertain" in dialog._status.get()
    review.registry.run_all()
    assert _rows(review.writer) == []


def test_severity_is_optional_and_a_bad_subject_count_is_refused(review):
    dialog = _open(review)
    _record(dialog)
    assert dialog._findings[0][0].severity is None
    for bad in ("0", "13", "-1", "two", "1.5", "２"):
        dialog._subjects.set(bad)
        dialog._save_inspection("defects_confirmed")
        assert "Subjects in image" in dialog._status.get()
    review.registry.run_all()
    assert _rows(review.writer) == []
    dialog._findings[0] = replace(dialog._findings[0][0], severity=Severity.MINOR), None
    dialog._subjects.set("")
    dialog._save_inspection("defects_confirmed")
    review.registry.run_all()
    (row,) = _rows(review.writer)
    assert row["metadata"]["subject_count"] is None
    assert row["metadata"]["findings"][0]["severity"] == "minor"


# --------------------------------------------------------------------------------------------------------- refusals


def test_refused_when_the_image_changed_since_the_dialog_opened(review):
    dialog = _open(review)
    _record(dialog)
    source = review.sources[0]
    make_image(source, 3)  # a different image now lives at the same path
    dialog._save_inspection("defects_confirmed")
    review.registry.run_all()
    assert _rows(review.writer) == []
    assert "image changed" in dialog._status.get()
    assert "inspected" not in _row_text(review, source)


def test_refused_for_an_image_that_is_not_a_still_image(review):
    dialog = _open(review)
    loaded = dialog._loaded
    animated = replace(loaded.source.identity, image_format="GIF")
    dialog._loaded = replace(loaded, source=replace(loaded.source, identity=animated))
    dialog._save_inspection("no_defect_seen")
    review.registry.run_all()
    assert _rows(review.writer) == [] and "still images" in dialog._status.get()


def test_refused_when_the_item_is_hidden_by_visibility_mode(review):
    dialog = _open(review)
    review.tab._visibility_resolver = lambda: SimpleNamespace(
        is_visible=lambda _subject: False, redact_text=lambda text: text
    )
    dialog._save_inspection("no_defect_seen")
    review.registry.run_all()
    assert _rows(review.writer) == [] and "hidden" in dialog._status.get()


def test_hidden_content_never_reaches_a_saved_inspection(review):
    review.tab.on_content_visibility_mode_changed("sfw")
    payload = {"stage_manifest": {"stage": "txt2img", "final_prompt": "explicit nude"}}
    assert write_image_metadata(
        review.sources[0], build_contract_kv(payload, job_id="j", run_id="r", stage="txt2img")
    )
    review.tab.preview.model.visibility(active=True, shown=True)
    dialog = _open(review)
    assert not dialog.after_view.model.path
    dialog._save_inspection("no_defect_seen")
    review.registry.run_all()
    assert _rows(review.writer) == []


def test_not_saved_when_learning_evidence_is_not_connected(review):
    review.tab._resolve_evidence_writer = lambda: None  # type: ignore[method-assign]
    dialog = _open(review)
    assert not _enabled(dialog._clean_button) and "not connected" in dialog._inspection_note.get()
    dialog._save_inspection("no_defect_seen")
    review.registry.run_all()
    assert "not connected" in dialog._status.get() and _rows(review.writer) == []


def test_a_failed_write_is_reported_and_not_shown_as_saved(review, monkeypatch):
    dialog = _open(review)
    monkeypatch.setattr(
        "src.review.review_evidence.LearningRecordWriter.append_record", lambda *_: False
    )
    dialog._save_inspection("no_defect_seen")
    review.registry.run_all()
    assert "not saved" in dialog._status.get()
    assert "inspected" not in _row_text(review, review.sources[0])
    assert review.tab._inspection_undo == []


# ----------------------------------------------------------------------------------------------------------- undo


def test_undo_records_a_cleared_row_and_clears_the_indicator(review):
    dialog = _open(review)
    dialog._save_inspection("no_defect_seen")
    review.registry.run_all()
    source = review.sources[0]
    assert "(inspected: no defect)" in _row_text(review, source)
    review.tab._undo_last_action()
    review.registry.run_all()
    rows = _rows(review.writer)
    assert [row["metadata"]["verdict"] for row in rows] == ["no_defect_seen", "cleared"]
    assert "inspected" not in _row_text(review, source)
    assert "Undid the saved inspection" in review.tab._feedback_status_var.get()
    review.tab._undo_last_action()  # nothing further to undo; the file was never touched
    assert len(_rows(review.writer)) == 2
    assert review.tab._inspection_undo == [] and "inspection" not in review.tab._undo_order


def test_undo_order_interleaves_with_ratings_and_decisions(review):
    dialog = _open(review)
    dialog._save_inspection("no_defect_seen")
    review.registry.run_all()
    review.tab._decide_current("retain")
    review.registry.run_all()
    assert review.tab._undo_order[-2:] == ["inspection", "decision"]
    review.tab._undo_last_action()  # the decision first
    review.registry.run_all()
    sources = [row["metadata"]["source"] for row in _rows(review.writer)]
    assert sources.count("review_tab_inspection") == 1
    review.tab._undo_last_action()  # then the inspection
    review.registry.run_all()
    assert [
        r["metadata"]["verdict"] for r in _rows(review.writer) if "verdict" in r["metadata"]
    ] == [
        "no_defect_seen",
        "cleared",
    ]
