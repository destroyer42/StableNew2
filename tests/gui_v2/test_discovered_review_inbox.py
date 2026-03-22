"""PR-GUI-LEARN-041: UI regression tests for Discovered Review Inbox and Table.

All tests use the tk_root fixture (no mainloop, no blocking window).
Controller state-transition tests use a minimal LearningController stub.
"""

from __future__ import annotations

import tkinter as tk
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.gui.views.discovered_review_inbox_panel import DiscoveredReviewInboxPanel
from src.gui.views.discovered_review_table import DiscoveredReviewTable
from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState
from src.queue.job_model import JobStatus
from src.queue.job_history_store import JobHistoryEntry
from src.learning.discovered_review_models import (
    STATUS_CLOSED,
    STATUS_IGNORED,
    STATUS_IN_REVIEW,
    STATUS_WAITING_REVIEW,
    DiscoveredReviewExperiment,
    DiscoveredReviewHandle,
    DiscoveredReviewItem,
    RATING_UNRATED,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handle(
    group_id: str = "disc-abc",
    status: str = STATUS_WAITING_REVIEW,
    varying_fields: tuple[str, ...] = ("sampler",),
    item_count: int = 3,
    stage: str = "txt2img",
) -> DiscoveredReviewHandle:
    return DiscoveredReviewHandle(
        group_id=group_id,
        display_name=f"Group {group_id}",
        status=status,
        item_count=item_count,
        stage=stage,
        varying_fields=varying_fields,
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )


def _make_item(
    item_id: str | None = None,
    stage: str = "txt2img",
    model: str = "sd_xl_base.safetensors",
    sampler: str = "Euler",
    steps: int = 20,
    cfg_scale: float = 7.0,
    rating: int = RATING_UNRATED,
) -> DiscoveredReviewItem:
    return DiscoveredReviewItem(
        item_id=item_id or str(uuid.uuid4()),
        artifact_path="/tmp/fake.png",
        stage=stage,
        model=model,
        sampler=sampler,
        steps=steps,
        cfg_scale=cfg_scale,
        rating=rating,
    )


def _make_experiment(group_id: str = "disc-abc") -> DiscoveredReviewExperiment:
    items = [_make_item() for _ in range(3)]
    return DiscoveredReviewExperiment(
        group_id=group_id,
        display_name="Test Group",
        stage="txt2img",
        prompt_hash="abc123",
        input_lineage_key="key1",
        status=STATUS_WAITING_REVIEW,
        items=items,
        varying_fields=("sampler",),
    )


# ---------------------------------------------------------------------------
# DiscoveredReviewInboxPanel tests
# ---------------------------------------------------------------------------

@pytest.mark.gui
def test_inbox_panel_creates_without_error(tk_root: tk.Tk) -> None:
    panel = DiscoveredReviewInboxPanel(tk_root)
    panel.pack(fill="both", expand=True)
    assert isinstance(panel, DiscoveredReviewInboxPanel)
    panel.destroy()


@pytest.mark.gui
def test_inbox_panel_load_handles_active(tk_root: tk.Tk) -> None:
    panel = DiscoveredReviewInboxPanel(tk_root)
    handles = [
        _make_handle("g1", STATUS_WAITING_REVIEW),
        _make_handle("g2", STATUS_IN_REVIEW),
    ]
    panel.load_handles(handles)
    # Treeview should show 2 items (both active)
    children = panel._tree.get_children()
    assert len(children) == 2
    panel.destroy()


@pytest.mark.gui
def test_inbox_panel_filter_closed(tk_root: tk.Tk) -> None:
    panel = DiscoveredReviewInboxPanel(tk_root)
    handles = [
        _make_handle("g1", STATUS_WAITING_REVIEW),
        _make_handle("g2", STATUS_CLOSED),
    ]
    panel.load_handles(handles)
    # Switch to "closed" filter
    panel._status_filter_var.set("closed")
    panel._apply_filter()
    children = panel._tree.get_children()
    assert len(children) == 1
    assert children[0] == "g2"
    panel.destroy()


@pytest.mark.gui
def test_inbox_panel_filter_all(tk_root: tk.Tk) -> None:
    panel = DiscoveredReviewInboxPanel(tk_root)
    handles = [
        _make_handle("g1", STATUS_WAITING_REVIEW),
        _make_handle("g2", STATUS_CLOSED),
        _make_handle("g3", STATUS_IGNORED),
    ]
    panel.load_handles(handles)
    panel._status_filter_var.set("all")
    panel._apply_filter()
    assert len(panel._tree.get_children()) == 3
    panel.destroy()


@pytest.mark.gui
def test_inbox_panel_get_selected_returns_none_when_empty(tk_root: tk.Tk) -> None:
    panel = DiscoveredReviewInboxPanel(tk_root)
    panel.load_handles([])
    assert panel.get_selected_group_id() is None
    panel.destroy()


@pytest.mark.gui
def test_inbox_panel_set_scanning_updates_label(tk_root: tk.Tk) -> None:
    panel = DiscoveredReviewInboxPanel(tk_root)
    panel.set_scanning(True)
    assert "scan" in panel._scan_status_label.cget("text").lower()
    panel.set_scanning(False)
    panel.destroy()


@pytest.mark.gui
def test_inbox_panel_open_group_callback(tk_root: tk.Tk) -> None:
    opened: list[str] = []
    panel = DiscoveredReviewInboxPanel(tk_root, on_open_group=lambda gid: opened.append(gid))
    handles = [_make_handle("g1")]
    panel.load_handles(handles)
    panel._tree.selection_set("g1")
    panel._selected_group_id = "g1"  # selection_set doesn't fire events in tests
    panel._on_open_clicked()
    assert opened == ["g1"]
    panel.destroy()


@pytest.mark.gui
def test_inbox_panel_close_group_callback(tk_root: tk.Tk) -> None:
    closed: list[str] = []
    panel = DiscoveredReviewInboxPanel(tk_root, on_close_group=lambda gid: closed.append(gid))
    handles = [_make_handle("g1")]
    panel.load_handles(handles)
    panel._tree.selection_set("g1")
    panel._selected_group_id = "g1"
    panel._on_close_clicked()
    assert closed == ["g1"]
    panel.destroy()


@pytest.mark.gui
def test_inbox_panel_ignore_group_callback(tk_root: tk.Tk) -> None:
    ignored: list[str] = []
    panel = DiscoveredReviewInboxPanel(tk_root, on_ignore_group=lambda gid: ignored.append(gid))
    handles = [_make_handle("g1")]
    panel.load_handles(handles)
    panel._tree.selection_set("g1")
    panel._selected_group_id = "g1"
    panel._on_ignore_clicked()
    assert ignored == ["g1"]
    panel.destroy()


@pytest.mark.gui
def test_inbox_panel_rescan_callback(tk_root: tk.Tk) -> None:
    rescanned = [False]
    panel = DiscoveredReviewInboxPanel(tk_root, on_rescan=lambda: rescanned.__setitem__(0, True))
    panel._on_rescan_clicked()
    assert rescanned[0]
    panel.destroy()


@pytest.mark.gui
def test_inbox_panel_scan_folder_callback(tk_root: tk.Tk) -> None:
    picked = [False]
    panel = DiscoveredReviewInboxPanel(
        tk_root,
        on_pick_scan_root=lambda: picked.__setitem__(0, True),
    )
    panel._on_pick_scan_root_clicked()
    assert picked[0]
    panel.destroy()


@pytest.mark.gui
def test_inbox_panel_scan_root_label_updates(tk_root: tk.Tk, tmp_path) -> None:
    panel = DiscoveredReviewInboxPanel(tk_root)
    panel.set_scan_root(str(tmp_path / "Pipeline"))
    assert "Scan Root:" in panel._scan_root_var.get()
    assert "Pipeline" in panel._scan_root_var.get()
    panel.set_scan_root(None)
    assert panel._scan_root_var.get() == "Scan Root: Auto"
    panel.destroy()


@pytest.mark.gui
def test_inbox_panel_varying_fields_shown(tk_root: tk.Tk) -> None:
    panel = DiscoveredReviewInboxPanel(tk_root)
    handle = _make_handle("g1", varying_fields=("sampler", "cfg_scale"))
    panel.load_handles([handle])
    val = panel._tree.set("g1", "varying")  # column id is 'varying' not 'varying_fields'
    assert "sampler" in val
    panel.destroy()


# ---------------------------------------------------------------------------
# DiscoveredReviewTable tests
# ---------------------------------------------------------------------------

@pytest.mark.gui
def test_review_table_creates_without_error(tk_root: tk.Tk) -> None:
    table = DiscoveredReviewTable(tk_root)
    table.pack(fill="both", expand=True)
    assert isinstance(table, DiscoveredReviewTable)
    table.destroy()


@pytest.mark.gui
def test_review_table_load_items(tk_root: tk.Tk) -> None:
    table = DiscoveredReviewTable(tk_root, varying_fields=["sampler"])
    items = [_make_item(sampler="Euler"), _make_item(sampler="DPM++")]
    table.load_items(items, varying_fields=["sampler"])
    assert len(table._tree.get_children()) == 2
    table.destroy()


@pytest.mark.gui
def test_review_table_empty_load(tk_root: tk.Tk) -> None:
    table = DiscoveredReviewTable(tk_root)
    table.load_items([])
    assert len(table._tree.get_children()) == 0
    table.destroy()


@pytest.mark.gui
def test_review_table_get_selected_none_when_empty(tk_root: tk.Tk) -> None:
    table = DiscoveredReviewTable(tk_root)
    assert table.get_selected_item_id() is None
    table.destroy()


@pytest.mark.gui
def test_review_table_rate_button_fires_callback(tk_root: tk.Tk) -> None:
    rated: list[tuple[str, int]] = []

    def _rate(item_id: str, rating: int) -> None:
        rated.append((item_id, rating))

    table = DiscoveredReviewTable(tk_root, on_rate_item=_rate)
    item = _make_item(item_id="item-1")
    table.load_items([item])
    table._tree.selection_set("item-1")
    table._apply_rating(4)
    assert rated == [("item-1", 4)]
    table.destroy()


@pytest.mark.gui
def test_review_table_refresh_item_rating(tk_root: tk.Tk) -> None:
    table = DiscoveredReviewTable(tk_root)
    item = _make_item(item_id="item-2")
    table.load_items([item])
    table.refresh_item_rating("item-2", 5)
    rating_cell = table._tree.set("item-2", "rating")
    assert "★" in rating_cell
    table.destroy()


@pytest.mark.gui
def test_review_table_header_updates_on_load(tk_root: tk.Tk) -> None:
    table = DiscoveredReviewTable(tk_root)
    table.load_items([], group_display_name="My Group")
    assert "My Group" in table._header_label.cget("text")
    table.destroy()


@pytest.mark.gui
def test_review_table_reload_clears_previous_rows(tk_root: tk.Tk) -> None:
    table = DiscoveredReviewTable(tk_root)
    table.load_items([_make_item(), _make_item()])
    assert len(table._tree.get_children()) == 2
    table.load_items([_make_item()])
    assert len(table._tree.get_children()) == 1
    table.destroy()


@pytest.mark.gui
def test_review_table_load_items_selects_first_item_and_updates_preview(tk_root: tk.Tk) -> None:
    table = DiscoveredReviewTable(tk_root)
    item = _make_item(item_id="item-preview")
    table.load_items([item])
    assert table.get_selected_item_id() == "item-preview"
    assert table._preview_thumbnail._current_path == item.artifact_path
    assert "txt2img" in table._preview_meta_var.get()
    table.destroy()


@pytest.mark.gui
def test_review_table_empty_load_clears_preview(tk_root: tk.Tk) -> None:
    table = DiscoveredReviewTable(tk_root)
    table.load_items([_make_item(item_id="item-preview")])
    table.load_items([])
    assert table.get_selected_item_id() is None
    assert table._preview_thumbnail._current_path is None
    assert "select an item" in table._preview_meta_var.get().lower()
    table.destroy()


# ---------------------------------------------------------------------------
# LearningController discovered-review orchestration tests
# ---------------------------------------------------------------------------

def _make_controller():
    """Build a minimal LearningController that passes the init guard."""
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState

    pipeline_controller = MagicMock()
    state = LearningState()
    ctrl = LearningController(
        learning_state=state,
        pipeline_controller=pipeline_controller,
    )
    return ctrl


def test_controller_refresh_discovered_inbox_empty(tmp_path) -> None:
    ctrl = _make_controller()
    # Patch the store root so we use a temp dir
    from src.learning.discovered_review_store import DiscoveredReviewStore
    ctrl._discovered_review_store = DiscoveredReviewStore(tmp_path)
    handles = ctrl.refresh_discovered_inbox()
    assert handles == []


def test_controller_load_discovered_group_returns_none_for_missing(tmp_path) -> None:
    ctrl = _make_controller()
    from src.learning.discovered_review_store import DiscoveredReviewStore
    ctrl._discovered_review_store = DiscoveredReviewStore(tmp_path)
    result = ctrl.load_discovered_group("disc-nonexistent")
    assert result is None
    assert ctrl.learning_state.selected_discovered_group_id is None


def test_controller_load_discovered_group_sets_state(tmp_path) -> None:
    ctrl = _make_controller()
    from src.learning.discovered_review_store import DiscoveredReviewStore
    store = DiscoveredReviewStore(tmp_path)
    ctrl._discovered_review_store = store
    exp = _make_experiment("disc-abc")
    store.save_group(exp)
    loaded = ctrl.load_discovered_group("disc-abc")
    assert loaded is not None
    assert loaded.group_id == "disc-abc"
    assert ctrl.learning_state.selected_discovered_group_id == "disc-abc"


def test_controller_close_discovered_group(tmp_path) -> None:
    ctrl = _make_controller()
    from src.learning.discovered_review_store import DiscoveredReviewStore
    store = DiscoveredReviewStore(tmp_path)
    ctrl._discovered_review_store = store
    exp = _make_experiment("disc-abc")
    store.save_group(exp)
    ctrl.close_discovered_group("disc-abc")
    loaded = store.load_group("disc-abc")
    assert loaded.status == STATUS_CLOSED


def test_controller_ignore_discovered_group(tmp_path) -> None:
    ctrl = _make_controller()
    from src.learning.discovered_review_store import DiscoveredReviewStore
    store = DiscoveredReviewStore(tmp_path)
    ctrl._discovered_review_store = store
    exp = _make_experiment("disc-abc")
    store.save_group(exp)
    ctrl.ignore_discovered_group("disc-abc")
    loaded = store.load_group("disc-abc")
    assert loaded.status == STATUS_IGNORED


def test_controller_reopen_discovered_group(tmp_path) -> None:
    ctrl = _make_controller()
    from src.learning.discovered_review_store import DiscoveredReviewStore
    store = DiscoveredReviewStore(tmp_path)
    ctrl._discovered_review_store = store
    exp = _make_experiment("disc-close")
    store.save_group(exp)
    store.close_group("disc-close")
    ctrl.reopen_discovered_group("disc-close")
    loaded = store.load_group("disc-close")
    assert loaded.status == STATUS_WAITING_REVIEW


def test_controller_save_discovered_item_rating(tmp_path) -> None:
    ctrl = _make_controller()
    from src.learning.discovered_review_store import DiscoveredReviewStore
    store = DiscoveredReviewStore(tmp_path)
    ctrl._discovered_review_store = store
    exp = _make_experiment("disc-rate")
    store.save_group(exp)
    item_id = exp.items[0].item_id
    ctrl.save_discovered_item_rating("disc-rate", item_id, 4, "nice")
    loaded = store.load_group("disc-rate")
    found = next(i for i in loaded.items if i.item_id == item_id)
    assert found.rating == 4
    assert found.rating_notes == "nice"


def test_controller_refresh_inbox_filters_active(tmp_path) -> None:
    ctrl = _make_controller()
    from src.learning.discovered_review_store import DiscoveredReviewStore
    store = DiscoveredReviewStore(tmp_path)
    ctrl._discovered_review_store = store

    active = _make_experiment("disc-active")
    closed = _make_experiment("disc-closed")
    store.save_group(active)
    store.save_group(closed)
    store.close_group("disc-closed")

    active_handles = ctrl.refresh_discovered_inbox(status="active")
    assert len(active_handles) == 1
    assert active_handles[0].group_id == "disc-active"

    all_handles = ctrl.refresh_discovered_inbox()
    assert len(all_handles) == 2


def test_controller_trigger_background_scan_noop_on_missing_root(tmp_path) -> None:
    """trigger_background_scan should not crash given a nonexistent output dir."""
    ctrl = _make_controller()
    from src.learning.discovered_review_store import DiscoveredReviewStore
    store = DiscoveredReviewStore(tmp_path)
    ctrl._discovered_review_store = store

    completed: list[int] = []
    import threading
    done = threading.Event()

    def _cb(n: int) -> None:
        completed.append(n)
        done.set()

    ctrl.trigger_background_scan(
        output_root=str(tmp_path / "no_such_dir"),
        on_complete=_cb,
    )
    done.wait(timeout=5.0)
    assert len(completed) == 1  # callback fires even with empty scan


def test_controller_load_staged_curation_group_returns_projection(tmp_path) -> None:
    ctrl = _make_controller()
    from src.learning.discovered_review_store import DiscoveredReviewStore

    store = DiscoveredReviewStore(tmp_path)
    ctrl._discovered_review_store = store
    exp = _make_experiment("disc-curation")
    store.save_group(exp)

    payload = ctrl.load_staged_curation_group("disc-curation")

    assert payload is not None
    assert payload["workflow"].workflow_id == "curation:disc-curation"
    assert len(payload["candidates"]) == len(exp.items)
    loaded = store.load_group("disc-curation")
    assert loaded.status == STATUS_IN_REVIEW


def test_controller_get_staged_curation_workflow_summary_returns_decision_counts(tmp_path) -> None:
    ctrl = _make_controller()
    from src.learning.discovered_review_store import DiscoveredReviewStore

    store = DiscoveredReviewStore(tmp_path)
    ctrl._discovered_review_store = store
    exp = _make_experiment("disc-curation")
    store.save_group(exp)
    ctrl.record_staged_curation_selection(
        "disc-curation",
        exp.items[0].item_id,
        "advanced_to_refine",
        reason_tags=["good_composition"],
    )

    summary = ctrl.get_staged_curation_workflow_summary("disc-curation")

    assert summary is not None
    assert summary["workflow_id"] == "curation:disc-curation"
    assert summary["decision_counts"] == {"advanced_to_refine": 1}
    assert summary["reason_tag_counts"] == {"good_composition": 1}


def test_controller_record_staged_curation_selection_persists_event(tmp_path) -> None:
    from src.learning.learning_record import LearningRecordWriter
    from src.learning.discovered_review_store import DiscoveredReviewStore

    writer = LearningRecordWriter(tmp_path / "learning_records.jsonl")
    ctrl = LearningController(
        learning_state=LearningState(),
        pipeline_controller=MagicMock(),
        learning_record_writer=writer,
    )
    store = DiscoveredReviewStore(tmp_path)
    ctrl._discovered_review_store = store
    exp = _make_experiment("disc-curation")
    store.save_group(exp)

    event = ctrl.record_staged_curation_selection(
        "disc-curation",
        exp.items[0].item_id,
        "advanced_to_refine",
        reason_tags=["good_composition"],
        notes="promote this one",
    )

    assert event is not None
    saved = store.load_selection_events("disc-curation")
    assert len(saved) == 1
    assert saved[0].reason_tags == ["good_composition"]
    assert saved[0].notes == "promote this one"
    records = writer.records_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(records) == 1
    assert "\"record_kind\": \"staged_curation_event\"" in records[0]


def test_controller_import_review_images_to_staged_curation(tmp_path) -> None:
    ctrl = _make_controller()
    from src.learning.discovered_review_store import DiscoveredReviewStore
    from src.utils.image_metadata import ReadPayloadResult

    store = DiscoveredReviewStore(tmp_path / "discovered")
    ctrl._discovered_review_store = store
    image_path = tmp_path / "import.png"
    image_path.write_text("placeholder", encoding="utf-8")
    payload = {
        "stage_manifest": {
            "stage": "txt2img",
            "config": {"sampler_name": "DPM++ 2M", "scheduler": "Karras", "steps": 30, "cfg_scale": 6.5},
        },
        "generation": {"width": 1024, "height": 1536},
        "job_id": "job-import-1",
        "run_id": "run-import-1",
    }

    with patch(
        "src.gui.controllers.learning_controller.extract_embedded_metadata",
        return_value=ReadPayloadResult(payload=payload, status="ok"),
    ), patch(
        "src.gui.controllers.learning_controller.resolve_prompt_fields",
        return_value=("prompt text", "negative text"),
    ), patch(
        "src.gui.controllers.learning_controller.resolve_model_vae_fields",
        return_value=("juggernautXL", "Automatic"),
    ):
        group_id = ctrl.import_review_images_to_staged_curation([str(image_path)], display_name="Imported Group")

    assert group_id is not None
    experiment = store.load_group(group_id)
    assert experiment is not None
    assert experiment.display_name == "Imported Group"
    assert len(experiment.items) == 1
    assert experiment.items[0].model == "juggernautXL"


def test_controller_import_history_entry_to_staged_curation(tmp_path) -> None:
    ctrl = _make_controller()
    from src.learning.discovered_review_store import DiscoveredReviewStore
    from src.utils.image_metadata import ReadPayloadResult

    store = DiscoveredReviewStore(tmp_path / "discovered")
    ctrl._discovered_review_store = store
    output_dir = tmp_path / "history-run"
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / "history.png"
    image_path.write_text("placeholder", encoding="utf-8")
    entry = JobHistoryEntry(
        job_id="history-1",
        created_at=datetime.utcnow(),
        status=JobStatus.COMPLETED,
        prompt_pack_id="History Pack",
        result={"output_dir": str(output_dir)},
    )
    payload = {
        "stage_manifest": {"stage": "txt2img", "config": {"steps": 20, "cfg_scale": 7.0}},
        "generation": {"width": 768, "height": 1152},
    }

    with patch(
        "src.gui.controllers.learning_controller.extract_embedded_metadata",
        return_value=ReadPayloadResult(payload=payload, status="ok"),
    ), patch(
        "src.gui.controllers.learning_controller.resolve_prompt_fields",
        return_value=("prompt text", "negative text"),
    ), patch(
        "src.gui.controllers.learning_controller.resolve_model_vae_fields",
        return_value=("juggernautXL", "Automatic"),
    ):
        group_id = ctrl.import_history_entry_to_staged_curation(entry)

    assert group_id is not None
    experiment = store.load_group(group_id)
    assert experiment is not None
    assert experiment.display_name == "History Import - History Pack"


def test_controller_set_staged_curation_face_triage_tier_persists_on_item(tmp_path) -> None:
    ctrl = _make_controller()
    from src.learning.discovered_review_store import DiscoveredReviewStore

    store = DiscoveredReviewStore(tmp_path)
    ctrl._discovered_review_store = store
    exp = _make_experiment("disc-face-tier")
    store.save_group(exp)

    saved = ctrl.set_staged_curation_face_triage_tier(
        "disc-face-tier",
        exp.items[0].item_id,
        "heavy",
    )

    assert saved is True
    loaded = store.load_group("disc-face-tier")
    assert loaded is not None
    assert loaded.items[0].extra_fields["face_triage_tier"] == "heavy"


def test_controller_submit_staged_curation_advancement_enqueues_face_triage_job(tmp_path) -> None:
    from src.learning.discovered_review_store import DiscoveredReviewStore
    from src.utils.image_metadata import ReadPayloadResult

    pipeline_controller = MagicMock()
    job_service = MagicMock()
    job_service.enqueue_njrs = MagicMock(return_value=["job-queued-1"])
    pipeline_controller._job_service = job_service
    pipeline_controller._config_manager = None
    ctrl = LearningController(
        learning_state=LearningState(),
        pipeline_controller=pipeline_controller,
    )
    store = DiscoveredReviewStore(tmp_path / "discovered")
    ctrl._discovered_review_store = store

    image_path = tmp_path / "candidate.png"
    image_path.write_text("placeholder", encoding="utf-8")
    exp = DiscoveredReviewExperiment(
        group_id="disc-face",
        display_name="Face Group",
        stage="txt2img",
        prompt_hash="hash-1",
        items=[
            DiscoveredReviewItem(
                item_id="cand-1",
                artifact_path=str(image_path),
                stage="txt2img",
                model="juggernautXL",
                sampler="DPM++ 2M",
                scheduler="Karras",
                steps=30,
                cfg_scale=6.5,
                positive_prompt="prompt text",
                negative_prompt="negative text",
                extra_fields={"face_triage_tier": "heavy"},
            )
        ],
        varying_fields=["cfg_scale"],
    )
    store.save_group(exp)
    ctrl.record_staged_curation_selection(
        "disc-face",
        "cand-1",
        "advanced_to_face_triage",
        reason_tags=["bad_face"],
        notes="needs rescue",
    )

    payload = {
        "stage_manifest": {
            "stage": "txt2img",
            "config": {
                "steps": 30,
                "cfg_scale": 6.5,
                "sampler_name": "DPM++ 2M",
                "scheduler": "Karras",
            },
        }
    }

    with patch(
        "src.gui.controllers.learning_controller.extract_embedded_metadata",
        return_value=ReadPayloadResult(payload=payload, status="ok"),
    ), patch(
        "src.gui.controllers.learning_controller.resolve_prompt_fields",
        return_value=("prompt text", "negative text"),
    ), patch(
        "src.gui.controllers.learning_controller.resolve_model_vae_fields",
        return_value=("juggernautXL", "Automatic"),
    ), patch(
        "src.gui.controllers.learning_controller.ConfigManager.get_setting",
        return_value="output",
    ):
        submitted = ctrl.submit_staged_curation_advancement("disc-face", "face_triage")

    assert submitted == 1
    assert job_service.enqueue_njrs.called
    submitted_records, run_request = job_service.enqueue_njrs.call_args[0]
    assert len(submitted_records) == 1
    record = submitted_records[0]
    assert record.start_stage == "adetailer"
    assert record.config["pipeline"]["output_route"] == "Learning"
    assert record.config["adetailer"]["adetailer_denoise"] == 0.34
    assert record.extra_metadata["curation"]["candidate_id"] == "cand-1"
    assert record.extra_metadata["selection_event"]["decision"] == "advanced_to_face_triage"
    assert run_request.requested_job_label == "Staged Curation: Face Triage"
